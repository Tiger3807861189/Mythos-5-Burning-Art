from __future__ import annotations

import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "src" / "shared" / "runtime"
sys.path.insert(0, str(RUNTIME))

from mythos_runtime.approval import AuthorityStore
from mythos_runtime.state import RuntimeStore
from mythos_runtime.storage import EventLog


class ConcurrencyTests(unittest.TestCase):
    def test_sequences_remain_monotonic_under_contention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = EventLog(Path(directory) / "events.jsonl")
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda value: log.append({"value": value}), range(40)))
            records = log.read_verified()
            self.assertEqual([item["sequence"] for item in records], list(range(1, 41)))
            self.assertEqual({item["payload"]["value"] for item in records}, set(range(40)))


    def test_initialize_is_singleton_under_contention_and_paths_are_short(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            state_root = root / "state"
            store = RuntimeStore(project, "m5-concurrent", root=state_root)
            with ThreadPoolExecutor(max_workers=8) as pool:
                states = list(pool.map(
                    lambda _: store.initialize(session_id="session-1", task_profile="build"),
                    range(24),
                ))
            self.assertTrue(all(item["last_sequence"] == 1 for item in states))
            records = store.log.read_verified()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["payload"]["operation"], "initialize")
            self.assertLess(len(str(store.paths["approval"])), 240)

    def test_authority_key_first_use_is_singleton_under_contention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            store = RuntimeStore(project, "key-race", root=root / "state")
            store.initialize(session_id="session-key", task_profile="build")
            authority = AuthorityStore(store.paths)
            with ThreadPoolExecutor(max_workers=8) as pool:
                keys = list(pool.map(lambda _: authority._key(), range(32)))
            self.assertTrue(all(key == keys[0] for key in keys))
            self.assertEqual(len(keys[0]), 32)
            self.assertEqual(store.paths["authority_key"].read_bytes(), keys[0])
    def test_distinct_project_identities_do_not_share_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            state_root = root / "state"
            left = RuntimeStore(first, "same-run", root=state_root)
            right = RuntimeStore(second, "same-run", root=state_root)
            self.assertNotEqual(left.identity, right.identity)
            self.assertNotEqual(left.paths["run"], right.paths["run"])
            left.initialize(session_id="left", task_profile="build")
            right.initialize(session_id="right", task_profile="repair")
            self.assertEqual(left.load()["session_id"], "left")
            self.assertEqual(right.load()["session_id"], "right")
if __name__ == "__main__":
    unittest.main()
