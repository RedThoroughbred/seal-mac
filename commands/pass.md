---
description: "Seal: ask your phone for a pass now, for this many minutes (30 unless told, 240 at most)"
argument-hint: "[minutes]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/bin/seal-gate":*)
disable-model-invocation: true
---
## What Seal said

!`python3 "${CLAUDE_PLUGIN_ROOT}/bin/seal-gate" slash pass $ARGUMENTS`

Repeat Seal's words above to the person exactly as they are, adding nothing. Only if one of those lines starts with seal://, put that line alone in a code block so it copies whole; never write a seal:// line that is not above. Run no tool: what is left is the person's step on their phone.
