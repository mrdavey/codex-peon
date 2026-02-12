#!/usr/bin/env python3
"""Codex notify hook + local CLI controls for codex-peon."""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("CODEX_PEON_DIR", str(Path.home() / ".codex" / "hooks" / "codex-peon")))
CONFIG_PATH = HOME / "config.json"
STATE_PATH = HOME / ".state.json"
PAUSED_PATH = HOME / ".paused"
PACKS_DIR = HOME / "packs"

DEFAULT_CONFIG: dict[str, Any] = {
    "active_pack": "peon",
    "volume": 0.5,
    "enabled": True,
    # Controls greeting behavior:
    # - launch: play only when using `codex-peon launch`
    # - turn_start: play on first completion of a thread / idle gap
    # - both: launch + turn_start
    # - off: disable greeting
    "greeting_mode": "launch",
    "categories": {
        "greeting": True,
        "acknowledge": True,
        "complete": True,
        "permission": True,
        "error": True,
        "resource_limit": True,
        "annoyed": True,
    },
    "annoyed_threshold": 3,
    "annoyed_window_seconds": 10,
    "session_start_idle_seconds": 120,
    "prevent_overlap": True,
    "cooldowns_seconds": {
        "default": 0,
        "greeting": 0,
        "acknowledge": 0,
        "complete": 0,
        "permission": 0,
        "error": 0,
        "resource_limit": 0,
        "annoyed": 0,
    },
    "keywords": {
        "permission": [
            "needs your approval",
            "need your approval",
            "approval requested",
            "approve this",
            "approve the command",
            "approve running",
            "allow this command",
            "permission prompt",
        ],
        "error": [
            "error",
            "failed",
            "unable",
            "cannot",
            "can't",
            "denied",
            "permission denied",
            "not found",
            "timed out",
            "exception",
        ],
        "resource_limit": [
            "rate limit",
            "quota",
            "429",
            "token limit",
            "context length",
            "context window",
        ],
    },
}

CATEGORY_PRIORITY = ["resource_limit", "permission", "error"]
CATEGORY_FALLBACKS: dict[str, list[str]] = {
    "greeting": ["acknowledge", "complete"],
    "acknowledge": ["complete"],
    "complete": ["acknowledge"],
    "permission": ["acknowledge", "complete"],
    "error": ["acknowledge", "complete"],
    "resource_limit": ["acknowledge", "complete"],
    "annoyed": ["acknowledge", "complete"],
}
PREVIEW_CATEGORIES = ["greeting", "acknowledge", "complete", "permission", "error", "resource_limit", "annoyed"]
GREETING_MODES = {"launch", "turn_start", "both", "off"}
DEFAULT_STATE: dict[str, Any] = {
    "last_played": {},
    "last_category_ts": {},
    "seen_threads": [],
    "turn_timestamps": {},
    "last_event_ts": 0.0,
    "playback_pid": None,
}


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return dict(default)


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def _merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge(dst[key], value)
        else:
            dst[key] = value
    return dst


def load_config() -> dict[str, Any]:
    cfg = _merge(json.loads(json.dumps(DEFAULT_CONFIG)), _load_json(CONFIG_PATH, {}))
    # Keep config durable if missing/corrupt so users can edit it immediately.
    _save_json(CONFIG_PATH, cfg)
    return cfg


def load_state() -> dict[str, Any]:
    return _merge(json.loads(json.dumps(DEFAULT_STATE)), _load_json(STATE_PATH, {}))


def save_state(state: dict[str, Any]) -> None:
    _save_json(STATE_PATH, state)


def detect_platform() -> str:
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        rel = platform.release().lower()
        if "microsoft" in rel or "wsl" in rel:
            return "wsl"
        return "linux"
    return "unknown"


def _play_mac(sound: Path, volume: float) -> int | None:
    if not shutil.which("afplay"):
        return None
    proc = subprocess.Popen(
        ["afplay", "-v", str(volume), str(sound)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid


def _play_wsl(sound: Path, volume: float) -> int | None:
    if not shutil.which("powershell.exe"):
        return None
    if not shutil.which("wslpath"):
        return None

    win_path = subprocess.check_output(["wslpath", "-w", str(sound)], text=True).strip()
    win_path = win_path.replace("\\", "/")

    # MediaPlayer handles wav/mp3 and plays asynchronously after launch.
    ps_script = (
        "Add-Type -AssemblyName PresentationCore; "
        "$p = New-Object System.Windows.Media.MediaPlayer; "
        f"$p.Open([Uri]::new('file:///{win_path}')); "
        f"$p.Volume = {volume}; "
        "Start-Sleep -Milliseconds 150; "
        "$p.Play(); "
        "Start-Sleep -Seconds 3; "
        "$p.Close()"
    )
    proc = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid


def _play_linux(sound: Path) -> int | None:
    candidates = [
        ["paplay", str(sound)],
        ["aplay", str(sound)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(sound)],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return proc.pid
    return None


def play_sound(sound: Path, volume: float) -> int | None:
    plat = detect_platform()
    playback_pid: int | None = None
    if plat == "mac":
        playback_pid = _play_mac(sound, volume)
    elif plat == "wsl":
        playback_pid = _play_wsl(sound, volume)
    elif plat == "linux":
        playback_pid = _play_linux(sound)

    if playback_pid is None:
        # Fallback when no platform player exists.
        print("\a", end="", flush=True)
    return playback_pid


def list_packs() -> list[tuple[str, str]]:
    packs: list[tuple[str, str]] = []
    if not PACKS_DIR.exists():
        return packs
    for manifest in sorted(PACKS_DIR.glob("*/manifest.json")):
        try:
            with manifest.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        name = str(data.get("name") or manifest.parent.name)
        display_name = str(data.get("display_name") or name)
        packs.append((name, display_name))
    return packs


def load_manifest(pack: str) -> dict[str, Any] | None:
    manifest = PACKS_DIR / pack / "manifest.json"
    try:
        with manifest.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def infer_category(message: str, cfg: dict[str, Any]) -> str:
    text = (message or "").lower()
    keywords = cfg.get("keywords") or {}

    for category in CATEGORY_PRIORITY:
        terms = keywords.get(category) if isinstance(keywords, dict) else None
        if not isinstance(terms, list):
            continue
        for term in terms:
            if isinstance(term, str) and term and term.lower() in text:
                return category

    return "acknowledge"


def category_enabled(cfg: dict[str, Any], category: str) -> bool:
    cats = cfg.get("categories") or {}
    if not isinstance(cats, dict):
        return True
    return bool(cats.get(category, True))


def resolve_enabled_category(cfg: dict[str, Any], category: str) -> str:
    for candidate in [category, *CATEGORY_FALLBACKS.get(category, [])]:
        if category_enabled(cfg, candidate):
            return candidate
    return ""


def _clamped_float(raw: Any, default: float, minimum: float) -> float:
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _clamped_int(raw: Any, default: int, minimum: int) -> int:
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _greeting_mode(cfg: dict[str, Any]) -> str:
    raw = cfg.get("greeting_mode", "launch")
    if isinstance(raw, str):
        mode = raw.strip().lower()
        if mode in GREETING_MODES:
            return mode
    return "launch"


def _thread_key(payload: dict[str, Any]) -> str:
    raw = payload.get("thread-id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "__default__"


def _is_pid_running(raw_pid: Any) -> bool:
    try:
        pid = int(raw_pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _cooldown_seconds_for(cfg: dict[str, Any], category: str) -> float:
    cooldowns = cfg.get("cooldowns_seconds")
    if not isinstance(cooldowns, dict):
        return 0.0
    raw = cooldowns.get(category, cooldowns.get("default", 0))
    return _clamped_float(raw, default=0.0, minimum=0.0)


def _is_on_category_cooldown(
    cfg: dict[str, Any],
    state: dict[str, Any],
    category: str,
    now_ts: float,
) -> bool:
    cooldown_seconds = _cooldown_seconds_for(cfg, category)
    if cooldown_seconds <= 0:
        return False

    last_map = state.get("last_category_ts")
    if not isinstance(last_map, dict):
        last_map = {}
        state["last_category_ts"] = last_map

    try:
        last_ts = float(last_map.get(category, 0))
    except (TypeError, ValueError):
        last_ts = 0.0
    if last_ts <= 0:
        return False
    return (now_ts - last_ts) < cooldown_seconds


def _overlap_blocked(cfg: dict[str, Any], state: dict[str, Any]) -> bool:
    if not bool(cfg.get("prevent_overlap", True)):
        return False

    pid = state.get("playback_pid")
    if _is_pid_running(pid):
        return True

    # Clear stale value.
    state["playback_pid"] = None
    return False


def maybe_play_category(
    cfg: dict[str, Any],
    state: dict[str, Any],
    category: str,
    now_ts: float,
) -> bool:
    resolved_category = resolve_enabled_category(cfg, category)
    if not resolved_category:
        return False

    if _is_on_category_cooldown(cfg, state, resolved_category, now_ts):
        return False

    if _overlap_blocked(cfg, state):
        return False

    sound_path, used_category = pick_sound(cfg, state, resolved_category)
    if sound_path is None:
        return False

    volume = _clamped_float(cfg.get("volume", 0.5), default=0.5, minimum=0.0)
    volume = min(volume, 1.0)
    playback_pid = play_sound(sound_path, volume)

    last_category_ts = state.get("last_category_ts")
    if not isinstance(last_category_ts, dict):
        last_category_ts = {}
        state["last_category_ts"] = last_category_ts
    last_category_ts[used_category] = now_ts
    state["playback_pid"] = playback_pid
    return True


def _track_rapid_turns(
    state: dict[str, Any],
    thread_key: str,
    now_ts: float,
    window_seconds: float,
) -> int:
    window = max(1.0, window_seconds)
    turn_timestamps = state.get("turn_timestamps")
    if not isinstance(turn_timestamps, dict):
        turn_timestamps = {}
        state["turn_timestamps"] = turn_timestamps

    existing_raw = turn_timestamps.get(thread_key, [])
    existing = [t for t in existing_raw if isinstance(t, (int, float))]
    kept = [float(t) for t in existing if now_ts - float(t) <= window]
    kept.append(now_ts)
    # Keep bounded to prevent unbounded state growth.
    turn_timestamps[thread_key] = kept[-32:]
    return len(kept)


def _should_play_greeting(
    state: dict[str, Any],
    thread_key: str,
    now_ts: float,
    idle_seconds: float,
) -> bool:
    seen_threads = state.get("seen_threads")
    if not isinstance(seen_threads, list):
        seen_threads = []
        state["seen_threads"] = seen_threads

    known_thread = thread_key in seen_threads
    if not known_thread:
        seen_threads.append(thread_key)
        # Keep bounded.
        state["seen_threads"] = seen_threads[-256:]

    last_event = state.get("last_event_ts")
    try:
        last_event_ts = float(last_event)
    except (TypeError, ValueError):
        last_event_ts = 0.0
    state["last_event_ts"] = now_ts

    idle_window = max(1.0, idle_seconds)
    idle_gap = (now_ts - last_event_ts) >= idle_window if last_event_ts > 0 else True
    return (not known_thread) or idle_gap


def pick_sound(cfg: dict[str, Any], state: dict[str, Any], category: str) -> tuple[Path | None, str]:
    pack = str(cfg.get("active_pack") or "peon")
    manifest = load_manifest(pack)

    if manifest is None:
        pack = "peon"
        manifest = load_manifest(pack)

    if manifest is None:
        return None, category

    categories = manifest.get("categories") if isinstance(manifest, dict) else None
    if not isinstance(categories, dict):
        return None, category

    cat_order = [category, *CATEGORY_FALLBACKS.get(category, [])]
    for cat in cat_order:
        entry = categories.get(cat)
        if not isinstance(entry, dict):
            continue
        sounds = entry.get("sounds")
        if not isinstance(sounds, list) or not sounds:
            continue

        files = [
            s.get("file")
            for s in sounds
            if isinstance(s, dict) and isinstance(s.get("file"), str)
        ]
        files = [f for f in files if f]
        if not files:
            continue

        state_key = f"{pack}:{cat}"
        last = ((state.get("last_played") or {}).get(state_key)) if isinstance(state, dict) else None
        candidates = files if len(files) <= 1 else [f for f in files if f != last]
        if not candidates:
            candidates = files

        picked = random.choice(candidates)
        state.setdefault("last_played", {})[state_key] = picked
        sound_path = PACKS_DIR / pack / "sounds" / picked
        if sound_path.exists():
            return sound_path, cat
    return None, category


def handle_hook_payload(raw_payload: str) -> int:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return 0

    if payload.get("type") != "agent-turn-complete":
        return 0

    cfg = load_config()
    if not bool(cfg.get("enabled", True)):
        return 0

    if PAUSED_PATH.exists():
        return 0

    state = load_state()
    now_ts = time.time()
    thread_key = _thread_key(payload)
    rapid_count = _track_rapid_turns(
        state,
        thread_key,
        now_ts,
        _clamped_float(cfg.get("annoyed_window_seconds", 10), default=10.0, minimum=1.0),
    )
    is_session_start = _should_play_greeting(
        state,
        thread_key,
        now_ts,
        _clamped_float(cfg.get("session_start_idle_seconds", 120), default=120.0, minimum=1.0),
    )

    greeting_mode = _greeting_mode(cfg)
    should_greet_on_turn_start = greeting_mode in {"turn_start", "both"}

    message = payload.get("last-assistant-message")
    inferred_category = infer_category(message if isinstance(message, str) else "", cfg)
    if is_session_start and should_greet_on_turn_start:
        preferred_category = "greeting"
    else:
        annoyed_threshold = _clamped_int(cfg.get("annoyed_threshold", 3), default=3, minimum=2)
        if inferred_category in {"permission", "error", "resource_limit"}:
            preferred_category = inferred_category
        elif rapid_count >= annoyed_threshold and category_enabled(cfg, "annoyed"):
            preferred_category = "annoyed"
        else:
            preferred_category = inferred_category

    maybe_play_category(cfg, state, preferred_category, now_ts)
    save_state(state)
    return 0


def cmd_pause() -> int:
    PAUSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAUSED_PATH.touch(exist_ok=True)
    print("codex-peon: sounds paused")
    return 0


def cmd_resume() -> int:
    if PAUSED_PATH.exists():
        PAUSED_PATH.unlink()
    print("codex-peon: sounds resumed")
    return 0


def cmd_toggle() -> int:
    if PAUSED_PATH.exists():
        return cmd_resume()
    return cmd_pause()


def cmd_status() -> int:
    cfg = load_config()
    state = "paused" if PAUSED_PATH.exists() else "active"
    print(f"codex-peon: {state}, pack={cfg.get('active_pack', 'peon')}, enabled={bool(cfg.get('enabled', True))}")
    return 0


def cmd_packs() -> int:
    cfg = load_config()
    active = str(cfg.get("active_pack") or "peon")
    packs = list_packs()
    if not packs:
        print("No packs found. Re-run install.sh.", file=sys.stderr)
        return 1

    for name, display in packs:
        marker = " *" if name == active else ""
        print(f"  {name:24s} {display}{marker}")
    return 0


def cmd_pack(name: str | None) -> int:
    cfg = load_config()
    packs = [p[0] for p in list_packs()]
    if not packs:
        print("No packs found. Re-run install.sh.", file=sys.stderr)
        return 1

    if name:
        if name not in packs:
            print(f"Pack '{name}' not found. Available: {', '.join(packs)}", file=sys.stderr)
            return 1
        next_pack = name
    else:
        active = str(cfg.get("active_pack") or "peon")
        if active in packs:
            next_pack = packs[(packs.index(active) + 1) % len(packs)]
        else:
            next_pack = packs[0]

    cfg["active_pack"] = next_pack
    _save_json(CONFIG_PATH, cfg)

    manifest = load_manifest(next_pack) or {}
    display = manifest.get("display_name", next_pack)
    print(f"codex-peon: switched to {next_pack} ({display})")
    return 0


def cmd_preview(category: str) -> int:
    cfg = load_config()
    state = load_state()

    if category not in PREVIEW_CATEGORIES:
        print(f"Category must be one of: {', '.join(PREVIEW_CATEGORIES)}", file=sys.stderr)
        return 1

    sound_path, used_category = pick_sound(cfg, state, category)
    save_state(state)

    if sound_path is None:
        print(f"No sound found for category '{category}'.", file=sys.stderr)
        return 1

    try:
        volume = float(cfg.get("volume", 0.5))
    except (TypeError, ValueError):
        volume = 0.5
    volume = min(max(volume, 0.0), 1.0)

    play_sound(sound_path, volume)
    print(f"codex-peon: played {used_category} -> {sound_path.name}")
    return 0


def cmd_enable(flag: bool) -> int:
    cfg = load_config()
    cfg["enabled"] = flag
    _save_json(CONFIG_PATH, cfg)
    print("codex-peon: enabled" if flag else "codex-peon: disabled")
    return 0


def cmd_launch(codex_args: list[str]) -> int:
    cfg = load_config()
    if bool(cfg.get("enabled", True)) and not PAUSED_PATH.exists():
        greeting_mode = _greeting_mode(cfg)
        if greeting_mode in {"launch", "both"}:
            state = load_state()
            maybe_play_category(cfg, state, "greeting", time.time())
            save_state(state)

    codex_exe = shutil.which("codex")
    if not codex_exe:
        print("codex-peon: 'codex' executable not found on PATH", file=sys.stderr)
        return 1

    forward_args = list(codex_args)
    if forward_args and forward_args[0] == "--":
        forward_args = forward_args[1:]

    argv = [codex_exe, *forward_args]
    try:
        os.execv(codex_exe, argv)
    except OSError as exc:
        print(f"codex-peon: failed to exec codex: {exc}", file=sys.stderr)
        return 1
    return 0


_MISSING = object()


def _split_key_path(key: str) -> list[str]:
    return [part for part in key.split(".") if part]


def _get_nested_value(data: dict[str, Any], key: str) -> Any:
    cur: Any = data
    for part in _split_key_path(key):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _set_nested_value(data: dict[str, Any], key: str, value: Any) -> None:
    parts = _split_key_path(key)
    if not parts:
        raise ValueError("key cannot be empty")

    cur: dict[str, Any] = data
    for part in parts[:-1]:
        child = cur.get(part)
        if not isinstance(child, dict):
            child = {}
            cur[part] = child
        cur = child
    cur[parts[-1]] = value


def _parse_config_value(raw_value: str) -> Any:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value


def cmd_config_get(key: str | None) -> int:
    cfg = load_config()
    if key is None:
        print(json.dumps(cfg, indent=2))
        return 0

    value = _get_nested_value(cfg, key)
    if value is _MISSING:
        print(f"Config key not found: {key}", file=sys.stderr)
        return 1

    if isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2))
    else:
        print(value)
    return 0


def cmd_config_set(key: str, raw_value: str) -> int:
    cfg = load_config()
    value = _parse_config_value(raw_value)
    _set_nested_value(cfg, key, value)
    _save_json(CONFIG_PATH, cfg)
    print(f"codex-peon: set {key} = {json.dumps(value)}")
    return 0


def cmd_keywords_add(category: str, term: str) -> int:
    cfg = load_config()
    keywords = cfg.setdefault("keywords", {})
    if not isinstance(keywords, dict):
        keywords = {}
        cfg["keywords"] = keywords

    current = keywords.get(category)
    if not isinstance(current, list):
        current = []
        keywords[category] = current

    if term in current:
        print(f"codex-peon: keyword already present for {category}")
        return 0

    current.append(term)
    _save_json(CONFIG_PATH, cfg)
    print(f"codex-peon: added keyword to {category}: {term}")
    return 0


def cmd_keywords_remove(category: str, term: str) -> int:
    cfg = load_config()
    keywords = cfg.get("keywords")
    if not isinstance(keywords, dict):
        print(f"codex-peon: no keyword list for {category}")
        return 1

    current = keywords.get(category)
    if not isinstance(current, list) or term not in current:
        print(f"codex-peon: keyword not found for {category}: {term}")
        return 1

    keywords[category] = [x for x in current if x != term]
    _save_json(CONFIG_PATH, cfg)
    print(f"codex-peon: removed keyword from {category}: {term}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="codex-peon",
        description="Codex notify sound hook and controls.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("pause", help="Mute sounds")
    sub.add_parser("resume", help="Unmute sounds")
    sub.add_parser("toggle", help="Toggle mute")
    sub.add_parser("status", help="Show status")
    sub.add_parser("packs", help="List packs")

    pack_parser = sub.add_parser("pack", help="Switch pack (or cycle when omitted)")
    pack_parser.add_argument("name", nargs="?", help="Pack name")

    preview_parser = sub.add_parser("preview", help="Play a test sound")
    preview_parser.add_argument(
        "category",
        nargs="?",
        default="acknowledge",
        choices=PREVIEW_CATEGORIES,
    )

    sub.add_parser("enable", help="Enable hook playback")
    sub.add_parser("disable", help="Disable hook playback")

    launch_parser = sub.add_parser("launch", help="Play greeting (if enabled) and launch codex")
    launch_parser.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to codex. Use `--` to pass flags like `--help`.",
    )

    config_parser = sub.add_parser("config", help="Read/write config")
    config_sub = config_parser.add_subparsers(dest="config_command")

    config_get = config_sub.add_parser("get", help="Get config key (or full config)")
    config_get.add_argument("key", nargs="?", help="Dot path, e.g. volume or cooldowns_seconds.acknowledge")

    config_set = config_sub.add_parser("set", help="Set config key")
    config_set.add_argument("key", help="Dot path, e.g. volume")
    config_set.add_argument("value", help='Value as JSON literal or string, e.g. 0.7 or "true"')

    keywords_parser = config_sub.add_parser("keywords", help="Manage keyword lists")
    keywords_sub = keywords_parser.add_subparsers(dest="keywords_command")

    keywords_add = keywords_sub.add_parser("add", help="Add keyword")
    keywords_add.add_argument("category", help="Keyword category, e.g. permission")
    keywords_add.add_argument("term", help="Keyword term")

    keywords_remove = keywords_sub.add_parser("remove", help="Remove keyword")
    keywords_remove.add_argument("category", help="Keyword category, e.g. permission")
    keywords_remove.add_argument("term", help="Keyword term")

    return parser.parse_args(argv)


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1].lstrip().startswith("{"):
        return handle_hook_payload(sys.argv[1])

    args = parse_args(sys.argv[1:])

    if args.command == "pause":
        return cmd_pause()
    if args.command == "resume":
        return cmd_resume()
    if args.command == "toggle":
        return cmd_toggle()
    if args.command == "status":
        return cmd_status()
    if args.command == "packs":
        return cmd_packs()
    if args.command == "pack":
        return cmd_pack(args.name)
    if args.command == "preview":
        return cmd_preview(args.category)
    if args.command == "enable":
        return cmd_enable(True)
    if args.command == "disable":
        return cmd_enable(False)
    if args.command == "launch":
        return cmd_launch(args.codex_args)
    if args.command == "config":
        if args.config_command == "get":
            return cmd_config_get(args.key)
        if args.config_command == "set":
            return cmd_config_set(args.key, args.value)
        if args.config_command == "keywords":
            if args.keywords_command == "add":
                return cmd_keywords_add(args.category, args.term)
            if args.keywords_command == "remove":
                return cmd_keywords_remove(args.category, args.term)
            print("Usage: codex-peon config keywords <add|remove> <category> <term>", file=sys.stderr)
            return 1
        print("Usage: codex-peon config <get|set|keywords>", file=sys.stderr)
        return 1

    # argparse prints help automatically when no command is provided if `-h` is used;
    # for plain invocation we show help-like guidance.
    print("Usage: codex-peon <pause|resume|toggle|status|packs|pack|preview|enable|disable|launch|config>")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
