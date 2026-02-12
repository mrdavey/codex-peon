# codex-peon

Warcraft-style sound notifications for Codex CLI, adapted from [peon-ping](https://github.com/tonyyont/peon-ping), because Codex is better 💯

`codex-peon` installs a Codex `notify` hook and plays sounds from the same packs used by `peon-ping`.

Quick install (`curl | bash`):

```bash
curl -fsSL https://raw.githubusercontent.com/mrdavey/codex-peon/main/install.sh | bash
```

Then restart terminal.

## What it does

- Plays a `greeting` sound when Codex boots (via `codex-peon launch`).
- Plays an `acknowledge` sound for normal task completion.
- Detects `permission`, `error`, and `resource_limit` outcomes from the assistant's final message.
- Plays `annoyed` sounds when turns are submitted rapidly (configurable).
- Supports sound pack switching and pause/resume controls.

## How sounds are played

Codex currently calls `notify` on `agent-turn-complete`. `codex-peon` uses that payload as the trigger.

Sound pipeline:

1. Codex executes the configured `notify` command with an `agent-turn-complete` JSON payload.
2. `codex-peon.py` loads runtime config from `~/.codex/hooks/codex-peon/config.json`.
3. It loads persistent state from `~/.codex/hooks/codex-peon/.state.json` (thread history, timing, anti-repeat).
4. It selects a category based on thread/timing/message heuristics.
5. It resolves the active pack manifest and randomly selects a non-repeating sound from that category.
6. Noise controls are applied:
   - per-category cooldown (`cooldowns_seconds`)
   - optional overlap prevention (`prevent_overlap`) with scope (`overlap_scope`)
7. It plays audio with a platform backend:
   - macOS: `afplay`
   - WSL: `powershell.exe` media playback
   - Linux: `paplay` / `aplay` / `ffplay`
   - fallback: terminal bell (`\a`)
8. It saves updated state for next-turn routing.

## Event and routing model

Important: `notify` does not currently expose `agent-turn-start`; it exposes turn completion payloads.
Default greeting mode is therefore `launch` (play greeting before starting Codex via launcher command).

Category routing rules:

- `greeting`: launch-time greeting when using `codex-peon launch` (default). Optional turn-start mode is available via config.
- `permission` / `error` / `resource_limit`: keyword-based inference from `last-assistant-message`
- `annoyed`: applied for rapid turns (`annoyed_threshold` events within `annoyed_window_seconds`), unless an explicit `permission`/`error`/`resource_limit` classification is present
- `acknowledge`: default for normal completion

Category fallback:

- If a selected category is disabled or missing in a pack, fallback categories are attempted (for example `acknowledge`, then `complete` where applicable).

## Install

From a local clone:

```bash
bash install.sh
```

From GitHub (`curl | bash`):

```bash
curl -fsSL https://raw.githubusercontent.com/mrdavey/codex-peon/main/install.sh | bash
```

If you host the repo elsewhere, override the base URL:

```bash
CODEX_PEON_REPO_BASE="https://raw.githubusercontent.com/mrdavey/codex-peon/main" \
  curl -fsSL https://raw.githubusercontent.com/mrdavey/codex-peon/main/install.sh | bash
```

Installer behavior:

- Installs `codex-peon` into a writable directory already on your `PATH` when possible.
- Falls back to `~/.local/bin` and auto-adds it to shell startup files if needed.
- Configures Codex `notify` in `~/.codex/config.toml`.
- Installs a shell alias so `codex` runs `codex-peon launch` (boot greeting every time).

## Command reference

```bash
codex-peon status
codex-peon packs
codex-peon pack peon
codex-peon pack               # cycle to next pack
codex-peon preview greeting
codex-peon preview acknowledge
codex-peon preview annoyed
codex-peon launch
codex-peon launch -- --help
codex-peon pause
codex-peon resume
codex-peon toggle
codex-peon enable
codex-peon disable
codex-peon config get
codex-peon config get volume
codex-peon config set volume 0.7
codex-peon config set cooldowns_seconds.acknowledge 1.5
codex-peon config set prevent_overlap true
codex-peon config set overlap_scope global
codex-peon config keywords add permission "approve this command"
codex-peon config keywords remove permission "approve this command"
```

## Configuration

Runtime file:

- `~/.codex/hooks/codex-peon/config.json`

Key fields:

- `active_pack`: active sound pack directory name
- `volume`: non-negative float (`0.0` and above)
- `enabled`: global on/off
- `greeting_mode`: `launch` (default), `turn_start`, `both`, or `off`
- `categories.*`: enable/disable each routing category
- `annoyed_threshold`: number of rapid turns before `annoyed`
- `annoyed_window_seconds`: rapid-turn window length
- `session_start_idle_seconds`: idle gap to treat next completion as session start
- `prevent_overlap`: default `false`; when `true`, skip new playback if previous playback process is still running
- `overlap_scope`: `thread` (default, per thread/session) or `global` (all terminals/sessions)
- `cooldowns_seconds`: per-category minimum seconds between plays (`default` applies fallback)
- `keywords.*`: keyword lists for `permission`, `error`, `resource_limit` inference

Example noise control config:

```json
{
  "greeting_mode": "launch",
  "prevent_overlap": true,
  "overlap_scope": "thread",
  "cooldowns_seconds": {
    "default": 0,
    "acknowledge": 1.5,
    "annoyed": 4
  }
}
```

To make greeting play on turn start instead of launch:

```bash
codex-peon config set greeting_mode turn_start
```

To launch Codex with greeting every time:

```bash
codex-peon launch
```

After install, `codex` is already aliased to `codex-peon launch`.
If your current shell session was open before install, reload your shell config:

```bash
source ~/.zshrc   # or ~/.bashrc / ~/.profile
```

## Optional TUI bell for approvals

Codex TUI can emit unfocused-terminal notifications for approval prompts. You can combine that with `codex-peon`:

```toml
[tui]
notifications = ["approval-requested", "agent-turn-complete"]
notification_method = "bel"
```

## Development

Main files:

- `codex-peon.py`: hook handler + CLI controls + routing logic
- `install.sh`: installation/update + Codex config wiring
- `uninstall.sh`: cleanup of symlinks and config
- `config.json`: default runtime config
- `packs/*`: imported sound packs and manifests

Validation:

```bash
pnpm test
pnpm build
```

## Uninstall

```bash
bash ~/.codex/hooks/codex-peon/uninstall.sh
```

## Attribution

Sound packs and manifests are sourced from `tonyyont/peon-ping` (MIT). See `NOTICE`.
