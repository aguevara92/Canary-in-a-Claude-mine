---
name: canary-in-a-claude-mine
description: A one-word tripwire that tells you a Claude Code session is degrading before it starts making things up. Use when a session runs long, when replies start feeling off, when the user asks "is this session still good" or "why does every reply start with 🐤", or to read back at which turn a session slipped.
---

# Canary in a Claude mine

A long session fills the context window. The model does not fail loudly when that happens. It fails quietly, and the first thing it drops is the instruction that matters least. So this plugin gives it one that matters least on purpose, and watches it.

The instruction is one line, injected at session start:

> The very first characters of every message you write in a turn are `🐤` followed by a period: the first message after the user's prompt, the short lines before a tool call, and the final one. Before any greeting, heading or other word.

While the word is there, the model is still reading its instructions. The turn it goes missing, the session is degrading, and the next one or two replies are the ones to distrust. That is the whole trick. It comes from [agentsroom.dev](https://agentsroom.dev/blog/canary-trick-detect-ai-agent-degradation); the plugin adds the part that does not depend on a human noticing.

## What it does

1. **The instruction.** A `SessionStart` hook injects the line as context. Nothing to add to `CLAUDE.md`. It runs again after `/clear` and `/compact`, so the tripwire is re-armed every time the window is reset.
2. **The check.** A `Stop` hook reads the session transcript at the end of every turn and looks at the first word of the first and the last assistant message of the turn.
3. **The alarm.** On a miss it blocks the turn once and makes Claude do three things: update the session notes if the workspace keeps them, tell the user in one line that the canary dropped, and recommend `/compact` with a focus line (or `/clear` plus a tight re-brief).
4. **The record.** Every turn is logged to `~/.claude/canary-logs/<session>.log` with its turn number. After a few sessions you can read at which turn your sessions start to slip. That number is worth more than any rule of thumb about when to compact.

## Changing the word

Pick one that never appears in a normal reply. A word or a single emoji both work; ASCII art with `)` or a leading `>` does not, the matcher reads one token. Either:

```bash
echo Sparrow > ~/.claude/canary
```

or set `CANARY_WORD=Canary` in the `env` block of your Claude Code settings. `CANARY_DISABLE=1` silences both hooks, for batch runs. `CANARY_MAX_BLOCKS` (default 3) caps how many times a session can be blocked, so a broken setup cannot trap anyone.

## Reading the signal

- **Word present:** nothing to do.
- **Word missing, Claude says so:** treat the last two replies as suspect. Compact or clear. Re-brief with the current file, the goal and the decisions taken. A clean window with a tight brief beats a bloated one.
- **Word missing on turn 2 or 3:** that is not degradation, the instruction did not load. Check `/hooks` shows the plugin's SessionStart hook.

When the user asks at which turn a session slipped, read the log for that session and answer with the turn number of the first MISS.

## What it cannot do

- **It is a proxy, not a measurement.** A dropped word means attention has diluted. It does not prove the next answer is wrong, and a present word does not prove it is right. Expect the odd false alarm and the odd miss.
- **It cannot fix a bloated system prompt.** If `CLAUDE.md` is enormous, attention is diluted from turn one and no canary will tell you. Trimming the file is the fix. This only tells you when the session on top of it has gone stale.
- **It does not compact for you.** Hooks cannot run `/compact`. The user does that.
- **It only sees the main thread.** Subagents do not carry the instruction and are skipped. A degraded subagent is invisible to it.
- **It is one word of noise per reply.** That is the price. A word with meaning is easier to live with than a random name, and slightly easier for the model to keep, which may delay the warning by a turn.
