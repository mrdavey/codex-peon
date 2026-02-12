#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.codex/hooks/codex-peon"
CONFIG_FILE="$HOME/.codex/config.toml"
LOCAL_BIN_LINK="$HOME/.local/bin/codex-peon"
BIN_LINK_FILE="$INSTALL_DIR/.bin_link_path"

echo "=== codex-peon uninstall ==="

python3 - <<'PY' "$CONFIG_FILE" "$INSTALL_DIR"
import json
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
install_dir = Path(sys.argv[2])
expected = ["python3", str(install_dir / "codex-peon.py")]

if not config_path.exists():
    raise SystemExit(0)

text = config_path.read_text(encoding="utf-8")
lines = text.splitlines()

notify_re = re.compile(r"^\s*notify\s*=\s*(.+)$")
new_lines = []
removed = False
in_top = True

for line in lines:
    if re.match(r"^\s*\[[^\]]+\]\s*$", line):
        in_top = False
    if in_top:
        m = notify_re.match(line)
        if m:
            rhs = m.group(1).strip()
            try:
                parsed = json.loads(rhs)
            except json.JSONDecodeError:
                parsed = None
            if parsed == expected:
                removed = True
                continue
    new_lines.append(line)

if removed:
    config_path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
PY

if [ -L "$LOCAL_BIN_LINK" ]; then
  target="$(readlink "$LOCAL_BIN_LINK" || true)"
  if [ "$target" = "$INSTALL_DIR/codex-peon.sh" ]; then
    rm "$LOCAL_BIN_LINK"
  fi
fi

if [ -f "$BIN_LINK_FILE" ]; then
  BIN_LINK="$(cat "$BIN_LINK_FILE" 2>/dev/null || true)"
  if [ -n "$BIN_LINK" ] && [ -L "$BIN_LINK" ]; then
    target="$(readlink "$BIN_LINK" || true)"
    if [ "$target" = "$INSTALL_DIR/codex-peon.sh" ]; then
      rm -f "$BIN_LINK"
    fi
  fi
fi

for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
  [ -f "$rc" ] || continue
  python3 - <<'PY' "$rc"
import sys
from pathlib import Path

rc_path = Path(sys.argv[1])
start = "# >>> codex-peon codex alias >>>"
end = "# <<< codex-peon codex alias <<<"

text = rc_path.read_text(encoding="utf-8")
if text and not text.endswith("\n"):
    text += "\n"

lines = text.splitlines()
out = []
skip = False
changed = False
for line in lines:
    if line.strip() == start:
        skip = True
        changed = True
        continue
    if skip and line.strip() == end:
        skip = False
        continue
    if not skip:
        out.append(line)

if changed:
    rc_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY
done

python3 - <<'PY' "$INSTALL_DIR"
import shutil
import sys
from pathlib import Path

install_dir = Path(sys.argv[1])
if install_dir.exists():
    shutil.rmtree(install_dir)
PY

echo "codex-peon uninstalled."
