#!/usr/bin/env python3
"""The canary. Two hooks in one file, Python stdlib only.

  canary.py context   SessionStart: injects the one-line instruction as context.
  canary.py check     Stop: verifies the first and the last message of the turn
                      start with the word; blocks the turn once when either does not.

The idea (agentsroom.dev, "The canary trick"): a trivial instruction is the
first thing a model drops when its context degrades. So we give it one that is
trivial on purpose and watch for it. The turn it goes missing, the session is
one or two replies away from confident nonsense.

Config:
  CANARY_WORD        the word (default "🐤", a canary), case-insensitive; an emoji works
  ~/.claude/canary   same thing as a file, one word, if you prefer no env var
  CANARY_DISABLE     any value: both hooks exit silently (batch runs, CI)
  CANARY_MAX_BLOCKS  blocks per session before the check goes quiet (default 3)

A miss is logged as MISS-misplaced (word present, not first), MISS-unprimed (never
honoured this session) or MISS-drop (was honoured, now gone). Only a drop raises the
degradation alarm; the other two ask for the same reply with the word first, quietly.

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
        f"The very first characters of every message you write in a turn are `{w}` followed by a period: "
        "the first message after the user's prompt, the short lines before a tool call, and the final one. "
        "Before any greeting, heading or other word. Not at the end, not after a first line. "
        f"Right: `{w}. Hola. Journal ready.` Wrong: `Hola. Journal ready. ... {w}.` "
        "It is a prefix, never a sign-off. "
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


def turn_texts(path: str):
    """First and last non-empty text block written by the main-thread assistant
    since the last real user prompt, and the number of real user prompts seen so
    far (tool results do not count). Both ends are checked: the first is what the
    user reads first in the app, the last is the one furthest from the instruction."""
    first, last, turns = None, None, 0
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
                first, last = None, None
            elif kind == "assistant" and isinstance(content, list):
                for block in content:
                    if block.get("type") == "text" and block.get("text", "").strip():
                        if first is None:
                            first = block["text"]
                        last = block["text"]
    return first, last, turns


def first_word(text: str) -> str:
    head = re.sub(r"^[\s*_`>#\-]+", "", text)          # "**🐤.**" -> "🐤.**"
    return re.split(r"[\s.,:;!?)\]*_`]+", head, maxsplit=1)[0] if head else ""


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
    first_text, last_text, turns = turn_texts(path)
    if last_text is None:
        return 0

    first = first_word(first_text)
    final = first_word(last_text)
    hit_first = first.lower() == w.lower()
    hit_last = final.lower() == w.lower()
    hit = hit_first and hit_last

    session = payload.get("session_id") or "unknown"
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{session}.log")
    prior_hits = misses = 0
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                prior_hits += "\thit\t" in line
                misses += "\tMISS" in line

    # A miss is one of three things, and only the last one is the alarm:
    #   misplaced  the word is in the message, just not first (the turn-1 sign-off habit)
    #   unprimed   the word has never been honoured this session: the instruction did not
    #              take, there is no context to have degraded yet
    #   drop       the word was being honoured and now it is gone
    if hit:
        kind = "hit"
    elif w.lower() in (first_text + last_text).lower():
        kind = "MISS-misplaced"
    elif prior_hits == 0:
        kind = "MISS-unprimed"
    else:
        kind = "MISS-drop"
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\tturn={turns}\t{kind}\t"
                  f"first={first[:20]!r} last={final[:20]!r}\n")
    if hit:
        return 0

    max_blocks = int(os.environ.get("CANARY_MAX_BLOCKS", "3"))
    if misses + 1 > max_blocks:
        return 0

    which = "first" if not hit_first else "final"
    if kind == "MISS-drop":
        reason = (
            f"CANARY DROPPED: your {which} message of this turn did not start with the word '{w}' "
            f"(turn {turns}, after {prior_hits} turns where it did). That instruction is the tripwire "
            "for context degradation and it just went missing, which means this session is degrading. "
            "Do three things, in this order: (1) if this workspace keeps a journal or session notes, "
            "update them with what was done and what is open; (2) tell the user in one plain line that "
            "the canary dropped, that the last couple of replies deserve a second look, and that they "
            "should /compact with a one-line focus, or /clear and re-brief with the file, the goal "
            f"and the decisions; (3) start that message with '{w}.' and keep it short."
        )
    else:
        where = "at the end, not at the start" if kind == "MISS-misplaced" else "missing"
        reason = (
            f"CANARY PLACEMENT: '{w}.' must be the very first characters of every message you write in a "
            f"turn, and in your {which} message it was {where} (turn {turns}). This is not degradation, "
            f"the instruction just did not take yet. Send the same reply again with '{w}.' as its first "
            "characters. Do not mention the canary, do not add a warning, do not touch the journal for this."
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
