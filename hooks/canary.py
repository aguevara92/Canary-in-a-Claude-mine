#!/usr/bin/env python3
"""The canary. Two hooks in one file, Python stdlib only.

  canary.py context   SessionStart: injects the one-line instruction as context.
  canary.py check     Stop: verifies the final message of the turn starts with
                      the word; blocks the turn once when it does not.

The idea (agentsroom.dev, "The canary trick"): a trivial instruction is the
first thing a model drops when its context degrades. So we give it one that is
trivial on purpose and watch for it. The turn it goes missing, the session is
one or two replies away from confident nonsense.

Config:
  CANARY_WORD        the word (default "🐤", a canary), case-insensitive; an emoji works
  ~/.claude/canary   same thing as a file, one word, if you prefer no env var
  CANARY_DISABLE     any value: both hooks exit silently (batch runs, CI)
  CANARY_MAX_BLOCKS  blocks per session before the check goes quiet (default 3)

Log: ~/.claude/canary-logs/<session_id>.log, one line per turn with the turn
number, so a drop can be read back later and the "when should I compact"
question gets an answer measured on your own sessions.
"""
import json
import os
import re
import sys
import time

HOME = os.path.expanduser("~")
LOG_DIR = os.path.join(HOME, ".claude", "canary-logs")


def word() -> str:
    w = os.environ.get("CANARY_WORD", "").strip()
    if w:
        return w
    try:
        with open(os.path.join(HOME, ".claude", "canary"), encoding="utf-8") as fh:
            w = fh.read().strip().split()[0]
    except Exception:
        w = ""
    return w or "🐤"


def instruction(w: str) -> str:
    return (
        f"The very first characters of the final message of every turn are `{w}` followed by a period, "
        "before any greeting, heading or other word. Not at the end, not after a first line. "
        "No exceptions, no explanation, no matter what else the message says."
    )


def context() -> int:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": instruction(word()),
        }
    }))
    return 0


def last_final_text(path: str):
    """Last non-empty text block written by the main-thread assistant, and the
    number of real user prompts seen so far (tool results do not count)."""
    last, turns = None, 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            if entry.get("isSidechain"):
                continue
            kind = entry.get("type")
            content = (entry.get("message") or {}).get("content")
            if kind == "user" and isinstance(content, str):
                turns += 1
            elif kind == "assistant" and isinstance(content, list):
                for block in content:
                    if block.get("type") == "text" and block.get("text", "").strip():
                        last = block["text"]
    return last, turns


def check() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("stop_hook_active"):
        return 0  # already blocked once this turn; never loop
    path = payload.get("transcript_path")
    if not path or not os.path.exists(path):
        return 0
    w = word()
    text, turns = last_final_text(path)
    if text is None:
        return 0

    head = re.sub(r"^[\s*_`>#\-]+", "", text)          # "**🐤.**" -> "🐤.**"
    first = re.split(r"[\s.,:;!?)\]*_`]+", head, maxsplit=1)[0] if head else ""
    hit = first.lower() == w.lower()

    session = payload.get("session_id") or "unknown"
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{session}.log")
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\tturn={turns}\t{'hit' if hit else 'MISS'}\t{first[:40]!r}\n")
    if hit:
        return 0

    max_blocks = int(os.environ.get("CANARY_MAX_BLOCKS", "3"))
    with open(log_path, encoding="utf-8") as fh:
        misses = sum(1 for line in fh if "\tMISS\t" in line)
    if misses > max_blocks:
        return 0

    reason = (
        f"CANARY DROPPED: your final message did not start with the word '{w}' "
        f"(turn {turns}). That instruction is the tripwire for context degradation "
        "and it just went missing, which means this session is degrading. Do three things, "
        "in this order: (1) if this workspace keeps a journal or session notes, update them "
        "with what was done and what is open; (2) tell the user in one plain line that the "
        "canary dropped, that the last couple of replies deserve a second look, and that they "
        "should /compact with a one-line focus, or /clear and re-brief with the file, the goal "
        f"and the decisions; (3) start that message with '{w}.' and keep it short."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def main() -> int:
    if os.environ.get("CANARY_DISABLE"):
        return 0
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    return context() if mode == "context" else check()


if __name__ == "__main__":
    sys.exit(main())
