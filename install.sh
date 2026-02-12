#!/usr/bin/env bash
# codex-peon installer
# Supports local clone installs and curl|bash installs.
set -euo pipefail

INSTALL_DIR="$HOME/.codex/hooks/codex-peon"
CONFIG_FILE="$HOME/.codex/config.toml"
LOCAL_BIN_DIR="$HOME/.local/bin"
BIN_LINK_FILE="$INSTALL_DIR/.bin_link_path"
REPO_BASE="${CODEX_PEON_REPO_BASE:-https://raw.githubusercontent.com/mrdavey/codex-peon/main}"
PACKS="peon peon_fr peon_pl peasant peasant_fr ra2_soviet_engineer sc_battlecruiser sc_kerrigan"

updating=false
if [ -f "$INSTALL_DIR/codex-peon.py" ]; then
  updating=true
fi

if [ "$updating" = true ]; then
  echo "=== codex-peon updater ==="
else
  echo "=== codex-peon installer ==="
fi

detect_platform() {
  case "$(uname -s)" in
    Darwin) echo "mac" ;;
    Linux)
      if grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
      else
        echo "linux"
      fi
      ;;
    *) echo "unknown" ;;
  esac
}

choose_bin_dir() {
  local d

  # Prefer stable user-level or common system bin directories when they are already on PATH.
  for d in "$HOME/.local/bin" "$HOME/bin" "/usr/local/bin" "/opt/homebrew/bin"; do
    if [[ ":$PATH:" == *":$d:"* ]]; then
      mkdir -p "$d" 2>/dev/null || true
      if [ -d "$d" ] && [ -w "$d" ]; then
        printf '%s\n' "$d"
        return 0
      fi
    fi
  done

  # Otherwise, use the first writable existing PATH entry.
  local IFS=':'
  for d in $PATH; do
    [ -z "$d" ] && continue
    case "$d" in
      *"/.codex/tmp/"*) continue ;;
    esac
    if [ -d "$d" ] && [ -w "$d" ]; then
      printf '%s\n' "$d"
      return 0
    fi
  done

  # Final fallback. We'll add it to PATH in shell startup files below if needed.
  printf '%s\n' "$LOCAL_BIN_DIR"
}

ensure_local_bin_on_path() {
  local path_line='export PATH="$HOME/.local/bin:$PATH"'
  local rc="$SHELL_RC_FILE"

  [ -f "$rc" ] || touch "$rc"

  if ! grep -Fq "$path_line" "$rc"; then
    {
      echo ""
      echo "# Added by codex-peon installer"
      echo "$path_line"
    } >> "$rc"
    PATH_RC_UPDATED=true
    PATH_RC_FILE="$rc"
  fi
}

detect_shell_rc_file() {
  local shell_name
  shell_name="$(basename "${SHELL:-}")"
  case "$shell_name" in
    zsh)
      printf '%s\n' "$HOME/.zshrc"
      ;;
    bash)
      printf '%s\n' "$HOME/.bashrc"
      ;;
    *)
      printf '%s\n' "$HOME/.profile"
      ;;
  esac
}

ensure_codex_alias() {
  local rc="$SHELL_RC_FILE"
  local start_mark="# >>> codex-peon codex alias >>>"
  local end_mark="# <<< codex-peon codex alias <<<"
  local alias_line="alias codex='$INSTALL_DIR/codex-peon.sh launch'"

  [ -f "$rc" ] || touch "$rc"

  # Remove old block if present, then append a fresh one.
  python3 - <<'PY' "$rc" "$start_mark" "$end_mark"
import sys
from pathlib import Path

rc_path = Path(sys.argv[1])
start = sys.argv[2]
end = sys.argv[3]

text = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
if text and not text.endswith("\n"):
    text += "\n"

lines = text.splitlines()
out = []
skip = False
for line in lines:
    if line.strip() == start:
        skip = True
        continue
    if skip and line.strip() == end:
        skip = False
        continue
    if not skip:
        out.append(line)

rc_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY

  {
    echo ""
    echo "$start_mark"
    echo "$alias_line"
    echo "$end_mark"
  } >> "$rc"

  ALIAS_RC_FILE="$rc"
}

PLATFORM="$(detect_platform)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required"
  exit 1
fi

case "$PLATFORM" in
  mac)
    if ! command -v afplay >/dev/null 2>&1; then
      echo "Error: afplay not found (required on macOS)"
      exit 1
    fi
    ;;
  wsl)
    if ! command -v powershell.exe >/dev/null 2>&1; then
      echo "Error: powershell.exe not found (required on WSL)"
      exit 1
    fi
    if ! command -v wslpath >/dev/null 2>&1; then
      echo "Error: wslpath not found (required on WSL)"
      exit 1
    fi
    ;;
  linux)
    if ! command -v paplay >/dev/null 2>&1 \
      && ! command -v aplay >/dev/null 2>&1 \
      && ! command -v ffplay >/dev/null 2>&1; then
      echo "Error: install one audio player: paplay, aplay, or ffplay"
      exit 1
    fi
    ;;
  *)
    echo "Warning: unsupported platform ($PLATFORM). Install continues, fallback bell will be used."
    ;;
esac

SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ "${BASH_SOURCE[0]}" != "bash" ]; then
  CANDIDATE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
  if [ -f "$CANDIDATE/codex-peon.py" ]; then
    SCRIPT_DIR="$CANDIDATE"
  fi
fi

PREV_BIN_LINK=""
if [ -f "$BIN_LINK_FILE" ]; then
  PREV_BIN_LINK="$(cat "$BIN_LINK_FILE" 2>/dev/null || true)"
fi

mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/packs"

if [ -n "$SCRIPT_DIR" ]; then
  cp "$SCRIPT_DIR/codex-peon.py" "$INSTALL_DIR/"
  cp "$SCRIPT_DIR/codex-peon.sh" "$INSTALL_DIR/"
  cp "$SCRIPT_DIR/config.json" "$INSTALL_DIR/"
  cp "$SCRIPT_DIR/VERSION" "$INSTALL_DIR/"
  cp "$SCRIPT_DIR/uninstall.sh" "$INSTALL_DIR/"
  cp -R "$SCRIPT_DIR/packs/"* "$INSTALL_DIR/packs/"
else
  echo "Downloading from GitHub..."
  curl -fsSL "$REPO_BASE/codex-peon.py" -o "$INSTALL_DIR/codex-peon.py"
  curl -fsSL "$REPO_BASE/codex-peon.sh" -o "$INSTALL_DIR/codex-peon.sh"
  curl -fsSL "$REPO_BASE/config.json" -o "$INSTALL_DIR/config.json"
  curl -fsSL "$REPO_BASE/VERSION" -o "$INSTALL_DIR/VERSION"
  curl -fsSL "$REPO_BASE/uninstall.sh" -o "$INSTALL_DIR/uninstall.sh"

  for pack in $PACKS; do
    mkdir -p "$INSTALL_DIR/packs/$pack/sounds"
    curl -fsSL "$REPO_BASE/packs/$pack/manifest.json" -o "$INSTALL_DIR/packs/$pack/manifest.json"

    python3 - <<'PY' "$INSTALL_DIR/packs/$pack/manifest.json" "$REPO_BASE" "$pack" "$INSTALL_DIR"
import json
import os
import subprocess
import sys

manifest_path, repo_base, pack, install_dir = sys.argv[1:5]
with open(manifest_path, "r", encoding="utf-8") as fh:
    manifest = json.load(fh)

seen = set()
for category in manifest.get("categories", {}).values():
    for sound in category.get("sounds", []):
        file_name = sound.get("file")
        if not file_name or file_name in seen:
            continue
        seen.add(file_name)
        url = f"{repo_base}/packs/{pack}/sounds/{file_name}"
        out = os.path.join(install_dir, "packs", pack, "sounds", file_name)
        subprocess.check_call(["curl", "-fsSL", url, "-o", out])
PY
  done
fi

chmod +x "$INSTALL_DIR/codex-peon.py" "$INSTALL_DIR/codex-peon.sh" "$INSTALL_DIR/uninstall.sh"

PATH_RC_UPDATED=false
PATH_RC_FILE=""
ALIAS_RC_FILE=""
SHELL_RC_FILE="$(detect_shell_rc_file)"
BIN_DIR="$(choose_bin_dir)"
mkdir -p "$BIN_DIR"
BIN_LINK="$BIN_DIR/codex-peon"
ln -sf "$INSTALL_DIR/codex-peon.sh" "$BIN_LINK"
printf '%s\n' "$BIN_LINK" > "$BIN_LINK_FILE"

# Remove old symlink location from previous installs when it still points at codex-peon.
if [ -n "$PREV_BIN_LINK" ] && [ "$PREV_BIN_LINK" != "$BIN_LINK" ] && [ -L "$PREV_BIN_LINK" ]; then
  prev_target="$(readlink "$PREV_BIN_LINK" || true)"
  if [ "$prev_target" = "$INSTALL_DIR/codex-peon.sh" ]; then
    rm -f "$PREV_BIN_LINK"
  fi
fi

if [[ ":$PATH:" != *":$BIN_DIR:"* ]] && [ "$BIN_DIR" = "$LOCAL_BIN_DIR" ]; then
  ensure_local_bin_on_path
fi

ensure_codex_alias

python3 - <<'PY' "$CONFIG_FILE" "$INSTALL_DIR"
import json
import os
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
install_dir = Path(sys.argv[2])
config_path.parent.mkdir(parents=True, exist_ok=True)

if config_path.exists():
    text = config_path.read_text(encoding="utf-8")
else:
    text = ""

if text and not text.endswith("\n"):
    text += "\n"

lines = text.splitlines()
notify_line = "notify = " + json.dumps(["python3", str(install_dir / "codex-peon.py")])


def is_table_header(line: str) -> bool:
    return re.match(r"^\s*\[[^\]]+\]\s*$", line) is not None


def set_top_level_key(lines_in: list[str], key: str, value_line: str) -> list[str]:
    out: list[str] = []
    in_top = True
    found = False
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")

    for line in lines_in:
        if is_table_header(line):
            in_top = False

        if in_top and key_re.match(line):
            if not found:
                out.append(value_line)
                found = True
            # Drop duplicates.
            continue

        out.append(line)

    if not found:
        insert_at = 0
        while insert_at < len(out):
            stripped = out[insert_at].strip()
            if stripped == "" or stripped.startswith("#"):
                insert_at += 1
                continue
            break
        out.insert(insert_at, value_line)

    return out


new_lines = set_top_level_key(lines, "notify", notify_line)
config_path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
PY

sound_total=$(find "$INSTALL_DIR/packs" -type f \( -name '*.wav' -o -name '*.mp3' -o -name '*.ogg' \) | wc -l | tr -d ' ')

echo ""
echo "Installed codex-peon to: $INSTALL_DIR"
echo "Installed sounds: $sound_total"
echo "Command link: $BIN_LINK"
echo "Configured notify hook in: $CONFIG_FILE"
echo "Shell alias installed in: $ALIAS_RC_FILE"
echo ""
echo "Quick start:"
echo "  codex-peon status"
echo "  codex-peon packs"
echo "  codex-peon pack peon"
echo "  codex"
echo "  codex-peon preview greeting"
echo "  codex-peon preview acknowledge"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]] && [ "$BIN_DIR" = "$LOCAL_BIN_DIR" ]; then
  echo ""
  echo "PATH note:"
  if [ "$PATH_RC_UPDATED" = true ]; then
    echo "  Added $LOCAL_BIN_DIR to PATH in: $PATH_RC_FILE"
  fi
fi

echo ""
echo "For this current shell session, run:"
echo "  source \"$ALIAS_RC_FILE\""
if [ "$PATH_RC_UPDATED" = true ]; then
  echo "  export PATH=\"$LOCAL_BIN_DIR:\$PATH\""
fi

if [ "$updating" = false ]; then
  echo ""
  echo "Optional (approval prompt bell in unfocused terminal):"
  echo "  Add to ~/.codex/config.toml"
  echo "    [tui]"
  echo "    notifications = [\"approval-requested\", \"agent-turn-complete\"]"
  echo "    notification_method = \"bel\""
fi
