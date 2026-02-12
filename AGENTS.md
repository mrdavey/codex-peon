# AGENTS.md

## Scope
These instructions apply to the entire `codex-peon` repository.

## Project goal
`codex-peon` provides Warcraft-style sound notifications for Codex CLI by wiring a local script into Codex `notify`.

## Core constraints
- Keep runtime dependencies minimal: Python stdlib only for `codex-peon.py`.
- Keep installer/uninstaller portable Bash (`#!/usr/bin/env bash`, `set -euo pipefail`).
- Preserve attribution and licensing for imported sound packs (`NOTICE`, `LICENSE`).
- Do not remove or rewrite sound pack manifests unless explicitly requested.
- Keep defaults aligned between:
  - `config.json`
  - `DEFAULT_CONFIG` in `codex-peon.py`

## Codex event model constraints
- Codex `notify` currently delivers `agent-turn-complete` payloads.
- “Session start”, “permission needed”, and “rapid prompts/annoyed” behaviors are inferred from:
  - thread IDs
  - timing state in `.state.json`
  - keyword classification of `last-assistant-message`
- Do not claim native Codex events beyond this without verification.

## Platform support requirements
- macOS: `afplay`
- WSL: `powershell.exe` + `wslpath`
- Linux: one of `paplay`, `aplay`, or `ffplay`
- Keep fallback terminal bell behavior (`\a`) when no audio backend is available.

## Required checks
For feature additions or major refactors, run:

```bash
pnpm test
pnpm build
```

For installer/path changes, also run a temp-home smoke test:

```bash
tmp_home=$(mktemp -d)
HOME="$tmp_home" bash install.sh
HOME="$tmp_home" codex-peon status || HOME="$tmp_home" ~/.codex/hooks/codex-peon/codex-peon.sh status
HOME="$tmp_home" bash ~/.codex/hooks/codex-peon/uninstall.sh
```

## Documentation requirements
- Update `README.md` whenever user-facing behavior, commands, config keys, or install flow changes.
- Keep GitHub install URLs and default `REPO_BASE` in `install.sh` consistent.
