import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-peon.py"
_SPEC = importlib.util.spec_from_file_location("codex_peon_module", MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("failed to load codex-peon.py")
codex_peon = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(codex_peon)


ALL_CATEGORIES = [
    "greeting",
    "acknowledge",
    "complete",
    "permission",
    "error",
    "resource_limit",
    "annoyed",
]


class CodexPeonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self._configure_module_paths(self.home)
        self._write_minimal_pack("peon")
        self._write_default_config()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _configure_module_paths(self, home: Path) -> None:
        codex_peon.HOME = home
        codex_peon.CONFIG_PATH = home / "config.json"
        codex_peon.STATE_PATH = home / ".state.json"
        codex_peon.PAUSED_PATH = home / ".paused"
        codex_peon.PACKS_DIR = home / "packs"

    def _write_default_config(self) -> None:
        cfg = json.loads(json.dumps(codex_peon.DEFAULT_CONFIG))
        codex_peon._save_json(codex_peon.CONFIG_PATH, cfg)

    def _write_minimal_pack(self, pack_name: str) -> None:
        pack_dir = codex_peon.PACKS_DIR / pack_name
        sounds_dir = pack_dir / "sounds"
        sounds_dir.mkdir(parents=True, exist_ok=True)

        categories = {}
        for category in ALL_CATEGORIES:
            file_name = f"{category}.wav"
            (sounds_dir / file_name).write_bytes(b"")
            categories[category] = {"sounds": [{"file": file_name, "line": category}]}

        manifest = {
            "name": pack_name,
            "display_name": "Test Pack",
            "categories": categories,
        }
        codex_peon._save_json(pack_dir / "manifest.json", manifest)

    def _payload(self, thread_id: str, turn_id: str, message: str) -> str:
        payload = {
            "type": "agent-turn-complete",
            "thread-id": thread_id,
            "turn-id": turn_id,
            "cwd": "/tmp",
            "input-messages": ["do thing"],
            "last-assistant-message": message,
        }
        return json.dumps(payload)

    def _load_state(self) -> dict:
        return codex_peon._load_json(codex_peon.STATE_PATH, {})

    def _load_config(self) -> dict:
        return codex_peon._load_json(codex_peon.CONFIG_PATH, {})

    def test_default_mode_acknowledge_without_turn_start_greeting(self) -> None:
        with mock.patch.object(codex_peon, "play_sound", return_value=None) as mocked_play:
            codex_peon.handle_hook_payload(self._payload("thread-a", "0", "Done."))
            codex_peon.handle_hook_payload(self._payload("thread-a", "1", "Done."))

        state = self._load_state()
        keys = set((state.get("last_played") or {}).keys())
        self.assertIn("peon:acknowledge", keys)
        self.assertNotIn("peon:greeting", keys)
        self.assertEqual(mocked_play.call_count, 2)

    def test_turn_start_greeting_mode_plays_greeting(self) -> None:
        cfg = self._load_config()
        cfg["greeting_mode"] = "turn_start"
        codex_peon._save_json(codex_peon.CONFIG_PATH, cfg)

        with mock.patch.object(codex_peon, "play_sound", return_value=None):
            codex_peon.handle_hook_payload(self._payload("thread-a2", "0", "Done."))

        state = self._load_state()
        keys = set((state.get("last_played") or {}).keys())
        self.assertIn("peon:greeting", keys)

    def test_permission_priority_over_annoyed(self) -> None:
        cfg = self._load_config()
        cfg["annoyed_threshold"] = 2
        codex_peon._save_json(codex_peon.CONFIG_PATH, cfg)

        with mock.patch.object(codex_peon, "play_sound", return_value=None):
            codex_peon.handle_hook_payload(self._payload("thread-b", "0", "Done."))
            codex_peon.handle_hook_payload(
                self._payload("thread-b", "1", "I need your approval to run this command."),
            )

        state = self._load_state()
        keys = set((state.get("last_played") or {}).keys())
        self.assertIn("peon:permission", keys)
        self.assertNotIn("peon:annoyed", keys)

    def test_annoyed_when_turns_are_rapid(self) -> None:
        cfg = self._load_config()
        cfg["annoyed_threshold"] = 2
        codex_peon._save_json(codex_peon.CONFIG_PATH, cfg)

        with mock.patch.object(codex_peon, "play_sound", return_value=None):
            codex_peon.handle_hook_payload(self._payload("thread-c", "0", "Done."))
            codex_peon.handle_hook_payload(self._payload("thread-c", "1", "Done."))

        state = self._load_state()
        keys = set((state.get("last_played") or {}).keys())
        self.assertIn("peon:annoyed", keys)

    def test_fallback_to_complete_when_greeting_and_ack_disabled(self) -> None:
        cfg = self._load_config()
        cfg["categories"]["greeting"] = False
        cfg["categories"]["acknowledge"] = False
        cfg["categories"]["complete"] = True
        codex_peon._save_json(codex_peon.CONFIG_PATH, cfg)

        with mock.patch.object(codex_peon, "play_sound", return_value=None):
            codex_peon.handle_hook_payload(self._payload("thread-d", "0", "Done."))

        state = self._load_state()
        keys = set((state.get("last_played") or {}).keys())
        self.assertIn("peon:complete", keys)

    def test_category_cooldown_suppresses_repeat(self) -> None:
        cfg = self._load_config()
        cfg["cooldowns_seconds"]["acknowledge"] = 999
        codex_peon._save_json(codex_peon.CONFIG_PATH, cfg)

        state = codex_peon.load_state()
        state["seen_threads"] = ["thread-e"]
        state["last_event_ts"] = time.time()
        codex_peon.save_state(state)

        with mock.patch.object(codex_peon, "play_sound", return_value=None) as mocked_play:
            codex_peon.handle_hook_payload(self._payload("thread-e", "1", "Done."))
            codex_peon.handle_hook_payload(self._payload("thread-e", "2", "Done."))

        self.assertEqual(mocked_play.call_count, 1)

    def test_overlap_prevents_new_playback(self) -> None:
        cfg = self._load_config()
        cfg["prevent_overlap"] = True
        codex_peon._save_json(codex_peon.CONFIG_PATH, cfg)

        state = codex_peon.load_state()
        state["seen_threads"] = ["thread-f"]
        state["last_event_ts"] = time.time()
        state["playback_pid"] = os.getpid()
        codex_peon.save_state(state)

        with mock.patch.object(codex_peon, "play_sound", return_value=None) as mocked_play:
            codex_peon.handle_hook_payload(self._payload("thread-f", "1", "Done."))

        self.assertEqual(mocked_play.call_count, 0)

    def test_config_set_and_keywords_add_remove(self) -> None:
        self.assertEqual(codex_peon.cmd_config_set("volume", "0.7"), 0)
        cfg = self._load_config()
        self.assertEqual(cfg["volume"], 0.7)

        added = codex_peon.cmd_keywords_add("permission", "approve this command")
        self.assertEqual(added, 0)
        cfg = self._load_config()
        self.assertIn("approve this command", cfg["keywords"]["permission"])

        removed = codex_peon.cmd_keywords_remove("permission", "approve this command")
        self.assertEqual(removed, 0)
        cfg = self._load_config()
        self.assertNotIn("approve this command", cfg["keywords"]["permission"])

    def test_launch_plays_greeting_and_execs_codex(self) -> None:
        with mock.patch.object(codex_peon, "play_sound", return_value=None), mock.patch.object(
            codex_peon.shutil,
            "which",
            return_value="/usr/local/bin/codex",
        ), mock.patch.object(codex_peon.os, "execv", return_value=None) as mocked_exec:
            rc = codex_peon.cmd_launch(["--", "--help"])

        self.assertEqual(rc, 0)
        mocked_exec.assert_called_once_with("/usr/local/bin/codex", ["/usr/local/bin/codex", "--help"])
        state = self._load_state()
        keys = set((state.get("last_played") or {}).keys())
        self.assertIn("peon:greeting", keys)


if __name__ == "__main__":
    unittest.main()
