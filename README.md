# Canary in a Claude mine

A one-word tripwire for Claude Code sessions. Two hooks, one skill, no dependencies beyond Python 3.

Long sessions degrade quietly. The model drops its least important instruction first, so this plugin gives it one that is unimportant on purpose, and a hook that notices the moment it is gone. That moment is one or two replies before the session starts making things up.

## Install

```
/plugin marketplace add aguevara92/Canary-in-a-Claude-mine
/plugin install canary-in-a-claude-mine@canary-in-a-claude-mine
```

Try it without installing:

```bash
git clone https://github.com/aguevara92/Canary-in-a-Claude-mine
claude --plugin-dir Canary-in-a-Claude-mine
```

## What happens then

1. Every session starts with one injected instruction: begin the final message of every turn with the word `Canary` and a period. Nothing to add to your `CLAUDE.md`.
2. At the end of every turn a Stop hook reads the transcript and checks the first word of the final message.
3. The turn the word is missing, the hook blocks once and Claude has to tell you: the canary dropped, the last replies deserve a second look, compact or clear.
4. Every turn is logged to `~/.claude/canary-logs/<session>.log` with its turn number. After a few sessions that file tells you at which turn your sessions actually start to slip.

Change the word with `echo Sparrow > ~/.claude/canary`, or `CANARY_WORD` in your settings `env`. `CANARY_DISABLE=1` silences it for batch runs.

## What it cannot do

- It is a proxy, not a measurement. A dropped word means attention has diluted, not that the next answer is wrong. Expect the odd false alarm and the odd miss.
- It cannot fix a bloated `CLAUDE.md`. A huge system prompt dilutes attention from turn one and no canary sees that. Trim the file.
- It does not compact for you. Hooks cannot run `/compact`.
- It only sees the main thread. Subagents are skipped.
- It is one word of noise per reply. That is the price.

The full explainer and the log format live in [skills/canary-in-a-claude-mine/SKILL.md](skills/canary-in-a-claude-mine/SKILL.md).

## Credit

The trick is from [agentsroom.dev](https://agentsroom.dev/blog/canary-trick-detect-ai-agent-degradation). The hooks, the log and the packaging are this repo's addition. MIT.
