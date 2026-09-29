"""Behavioral checks using temporary, deliberately unfamiliar local projects."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "plugins/local-tool-registry/scripts/registry.py"
spec = importlib.util.spec_from_file_location("registry", SCRIPT)
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "projects"
        self.root.mkdir()
        self.data = self.base / "shared"
        self.reg = registry.Registry(self.data)
        self.reg.configure([str(self.root)])

    def project(self, name, description="Transforms records into a report."):
        path = self.root / name
        path.mkdir(parents=True)
        (path / "README.md").write_text("# " + name + "\n\n" + description + "\n", encoding="utf-8")
        return path

    def card(self, path, **extra):
        data = {"path": str(path), "name": "User provided label", "invocation": {"argv": [sys.executable, "entry.py", "{input}"], "cwd": ".", "required_env": []}}
        data.update(extra)
        return data

    def test_new_session_uses_shared_metadata_without_execution(self):
        path = self.project("river-mapper", "Turns geospatial waypoints into route previews.")
        marker = self.base / "executed"
        (path / "setup.py").write_text("open(" + repr(str(marker)) + ", 'w').write('executed')", encoding="utf-8")
        (path / "pyproject.toml").write_text('[project]\nname = "river-mapper"\ndescription = "Route preview generator"\n', encoding="utf-8")
        self.reg.scan()
        new_session = registry.Registry(self.data)
        result = new_session.list(query="请看看这些坐标能画成什么")
        self.assertEqual(result["total"], 1)
        tool = result["tools"][0]
        self.assertEqual(tool["status"], "candidate")
        self.assertEqual(tool["description"], "Route preview generator")
        self.assertIn(str((path / "README.md").resolve()), tool["metadata_paths"])
        self.assertIn("setup.py", tool["project_indicators"])
        self.assertFalse(marker.exists())

    def test_manifest_cannot_claim_verified_or_execute_commands(self):
        path = self.project("paper-lens")
        marker = self.base / "executed"
        (path / "tool-capability.json").write_text(json.dumps({"name": "Paper Lens", "status": "verified", "verified": True, "capabilities": ["Inspect scan quality"], "invocation": {"argv": [sys.executable, "-c", "open(" + repr(str(marker)) + ",'w').write('x')"]}}), encoding="utf-8")
        self.reg.scan()
        tool = self.reg.list()["tools"][0]
        self.assertEqual(tool["status"], "candidate")
        self.assertFalse(tool["health"]["functional_verification"])
        self.reg.doctor(tool["id"])
        self.assertEqual(self.reg.inspect(tool["id"])["tool"]["status"], "candidate")
        self.assertFalse(marker.exists())

    def test_register_override_survives_update_delete_and_restore(self):
        path = self.project("signal-cleaner", "Original description")
        entry = path / "entry.py"
        entry.write_text("raise RuntimeError('must never execute')", encoding="utf-8")
        self.reg.scan()
        before = self.reg.list()["tools"][0]
        registered = self.reg.register(self.card(path, description="A carefully reviewed summary", status="verified"))["tool"]
        self.assertEqual(registered["id"], before["id"])
        self.assertEqual(registered["status"], "configured")
        (path / "README.md").write_text("# Changed\n\nUpstream changed.", encoding="utf-8")
        self.reg.scan()
        changed = self.reg.inspect(before["id"])["tool"]
        self.assertEqual(changed["description"], "A carefully reviewed summary")
        self.assertNotEqual(changed["metadata_fingerprint"], before["metadata_fingerprint"])
        entry.unlink()
        self.reg.scan()
        self.assertEqual(self.reg.inspect(before["id"])["tool"]["status"], "unavailable")
        entry.write_text("print('restored')", encoding="utf-8")
        self.reg.scan()
        self.assertEqual(self.reg.inspect(before["id"])["tool"]["status"], "configured")
        moved = self.base / "moved-away"
        path.rename(moved)
        self.reg.scan()
        self.assertEqual(self.reg.inspect(before["id"])["tool"]["status"], "unavailable")
        moved.rename(path)
        self.reg.scan()
        self.assertEqual(self.reg.inspect(before["id"])["tool"]["status"], "configured")

    def test_missing_metadata_stays_unavailable_in_doctor(self):
        path = self.project("temporary-project")
        self.reg.scan()
        tool_id = self.reg.list()["tools"][0]["id"]
        (path / "README.md").unlink()
        self.reg.scan()
        self.assertEqual(self.reg.doctor(tool_id)["tools"][0]["status"], "unavailable")
        (path / "README.md").write_text("# Restored\n\nRestored project", encoding="utf-8")
        self.reg.scan()
        self.assertEqual(self.reg.inspect(tool_id)["tool"]["status"], "candidate")

    def test_scanning_is_bounded_and_does_not_follow_symlinks(self):
        self.project("visible")
        for skip in ("node_modules", ".venv", ".git"):
            folder = self.root / skip / "must-not-discover"
            folder.mkdir(parents=True)
            (folder / "README.md").write_text("Hidden dependency", encoding="utf-8")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "README.md").write_text("Outside directory", encoding="utf-8")
        (self.root / "escape").symlink_to(outside, target_is_directory=True)
        indirect = self.root / "indirect"
        indirect.mkdir()
        (indirect / "README.md").symlink_to(outside / "README.md")
        deep = self.root / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "README.md").write_text("Too deep", encoding="utf-8")
        self.reg.scan()
        self.assertEqual([x["name"] for x in self.reg.list()["tools"]], ["visible"])

    def test_malformed_metadata_and_fifo_do_not_abort_scan(self):
        bad = self.project("bad-json")
        (bad / "package.json").write_text("{broken", encoding="utf-8")
        (bad / "tool-capability.json").write_text('{"invocation":{"argv":"rm -rf /"}}', encoding="utf-8")
        if hasattr(os, "mkfifo"):
            fifo = self.root / "fifo"
            fifo.mkdir()
            os.mkfifo(fifo / "README.md")
        huge = self.root / "huge"
        huge.mkdir()
        (huge / "README.md").write_text("X" * (registry.MAX_METADATA_BYTES + 1), encoding="utf-8")
        self.reg.scan()
        tools = self.reg.list()["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(len(tools[0]["warnings"]), 2)
        self.assertEqual(tools[0]["status"], "candidate")

    def test_registration_rejects_env_values_and_does_not_save_secrets(self):
        path = self.project("credential-tool")
        (path / "entry.py").write_text("", encoding="utf-8")
        card = self.card(path)
        card["invocation"]["env"] = {"API_TOKEN": "secret-do-not-write"}
        with self.assertRaises(registry.RegistryError):
            self.reg.register(card)
        card["invocation"].pop("env")
        card["invocation"]["required_env"] = ["EXAMPLE_API_TOKEN"]
        with mock.patch.dict(os.environ, {"EXAMPLE_API_TOKEN": "secret-do-not-write"}):
            registered = self.reg.register(card)["tool"]
        self.assertEqual(registered["status"], "configured")
        self.assertNotIn("secret-do-not-write", self.reg.db_path.read_text(encoding="utf-8"))
        with mock.patch.dict(os.environ, {}, clear=True):
            result = self.reg.doctor(registered["id"])
        self.assertEqual(result["tools"][0]["status"], "unavailable")

    def test_forget_does_not_delete_and_survives_scans(self):
        path = self.project("forgotten")
        self.reg.scan()
        tool_id = self.reg.list()["tools"][0]["id"]
        self.reg.forget(tool_id)
        self.assertTrue(path.is_dir())
        self.reg.scan()
        self.assertEqual(self.reg.list()["total"], 0)
        self.reg.register({"path": str(path)})
        self.assertEqual(self.reg.list()["total"], 1)

    def test_corruption_never_silently_resets_registry(self):
        self.reg.db_path.write_text("{incomplete", encoding="utf-8")
        with self.assertRaises(registry.RegistryError) as caught:
            self.reg.scan()
        self.assertEqual(caught.exception.code, "registry_corrupt")
        self.assertEqual(self.reg.db_path.read_text(encoding="utf-8"), "{incomplete")

    def test_find_exposes_full_small_catalog_for_semantic_selection(self):
        for name in ("alpha", "bravo", "charlie"):
            self.project(name, "Opaque capability")
        self.reg.scan()
        result = self.reg.list(query="一个与元数据措辞不同的任务")
        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["tools"]), 3)
        self.assertEqual(result["selection_mode"], "bounded_catalog")
        self.assertEqual(result["status_counts"]["candidate"], 3)

    def test_cli_stdin_query_and_errors_are_json(self):
        query = "Please consider local tools for this task."
        result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data), "find", "--stdin-query"], input=query, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["query"], query)
        error = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data), "find", "--limit", "1000"], text=True, capture_output=True, timeout=10)
        self.assertNotEqual(error.returncode, 0)
        self.assertEqual(json.loads(error.stdout)["error"]["code"], "usage")
        self.assertEqual(error.stderr, "")

    def test_find_ranks_before_truncating_a_medium_catalog(self):
        for index in range(16):
            self.project("a-project-" + str(index), "General utility without matching terms")
        self.project("z-specialized", "Resamples laboratory signals using wavelets")
        self.reg.scan()
        result = self.reg.list(limit=12, query="wavelets")
        self.assertEqual(result["total"], 17)
        self.assertEqual(len(result["tools"]), 12)
        self.assertEqual(result["tools"][0]["name"], "z-specialized")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["selection_mode"], "lexical_candidates")

    def test_chinese_goal_without_tool_name_survives_catalog_truncation(self):
        for index in range(16):
            self.project("a-project-" + str(index), "数据库备份与日志轮转")
        self.project("z-unknown-tool", "将扫描文档识别为可搜索的文字")
        self.reg.scan()
        result = self.reg.list(limit=12, query="帮我把扫描文档里的文字提取出来")
        self.assertEqual(result["tools"][0]["name"], "z-unknown-tool")
        self.assertTrue(result["truncated"])

    def test_unfamiliar_platform_url_matches_without_named_tool(self):
        for index in range(16):
            self.project("a-project-" + str(index), "General backup utility")
        self.project("z-link-reader", "Extracts content from lantern.example.net URLs")
        self.reg.scan()
        result = self.reg.list(limit=12, query="获取这个页面的内容 https://lantern.example.net/item/7392")
        self.assertEqual(result["tools"][0]["name"], "z-link-reader")

    def test_concurrent_process_registrations_do_not_lose_updates(self):
        processes = []
        for index in range(10):
            path = self.project("parallel-" + str(index))
            card = self.base / ("card-" + str(index) + ".json")
            card.write_text(json.dumps({"path": str(path), "name": "Parallel " + str(index)}), encoding="utf-8")
            processes.append(subprocess.Popen([sys.executable, str(SCRIPT), "--data-dir", str(self.data), "register", "--file", str(card)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for process in processes:
            out, err = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, err + out)
            self.assertTrue(json.loads(out)["ok"])
        state = json.loads(self.reg.db_path.read_text(encoding="utf-8"))
        self.assertEqual(len(state["tools"]), 10)
        self.assertEqual(state["revision"], 11)
        self.assertEqual(list(self.data.glob(".registry-*.tmp")), [])

    def test_data_directory_is_shared_between_host_and_cli(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.base / "xdg"), "PLUGIN_DATA": str(self.base / "host-plugin")}, clear=True):
            self.assertEqual(registry.default_data_dir(), self.base / "xdg" / "local-tool-registry")
        with mock.patch.dict(os.environ, {"LTR_DATA_DIR": str(self.data), "XDG_DATA_HOME": str(self.base / "xdg")}, clear=True):
            self.assertEqual(registry.default_data_dir(), self.data)

    def test_read_commands_do_not_create_an_absent_data_directory(self):
        missing = self.base / "never-created" / "state"
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("Read operations must not mkdir")), mock.patch.object(registry, "file_lock", side_effect=AssertionError("Read operations must not acquire write locks")):
            reader = registry.Registry(missing)
            self.assertEqual(reader.list()["total"], 0)
            self.assertEqual(reader.list(query="inspect this input")["revision"], 0)
            with self.assertRaises(registry.RegistryError) as error:
                reader.inspect("missing")
            self.assertEqual(error.exception.code, "not_found")
        self.assertFalse(missing.parent.exists())
        for command in (["list"], ["find", "task"], ["inspect", "missing"]):
            result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(missing), *command], text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2 if command[0] == "inspect" else 0, result.stderr)
            json.loads(result.stdout)
            self.assertFalse(missing.parent.exists())

    def test_read_commands_never_open_a_write_handle_or_change_state(self):
        path = self.project("read-only-candidate")
        tool_id = self.reg.register({"path": str(path)})["tool"]["id"]
        before = self.reg.db_path.read_bytes()
        lock = self.data / ".registry.lock"
        stamps = (self.reg.db_path.stat().st_mtime_ns, lock.stat().st_mtime_ns)
        original_open = os.open

        def only_read_open(path, flags, *args, **kwargs):
            forbidden = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            self.assertEqual(flags & forbidden, 0, "Read operation opened a write-capable handle")
            return original_open(path, flags, *args, **kwargs)

        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("Unexpected mkdir")), mock.patch.object(registry, "file_lock", side_effect=AssertionError("Unexpected lock")), mock.patch.object(os, "open", side_effect=only_read_open):
            reader = registry.Registry(self.data)
            self.assertEqual(reader.list()["total"], 1)
            self.assertEqual(reader.list(query="a task")["total"], 1)
            self.assertEqual(reader.inspect(tool_id)["tool"]["id"], tool_id)
        self.assertEqual(self.reg.db_path.read_bytes(), before)
        self.assertEqual((self.reg.db_path.stat().st_mtime_ns, lock.stat().st_mtime_ns), stamps)

    @unittest.skipIf(os.name == "nt", "POSIX read-only file permissions")
    def test_cli_reads_when_directory_and_lock_are_not_writable(self):
        path = self.project("protected-candidate")
        tool_id = self.reg.register({"path": str(path)})["tool"]["id"]
        lock = self.data / ".registry.lock"
        before = self.reg.db_path.read_bytes()
        try:
            self.reg.db_path.chmod(0o444)
            lock.chmod(0)
            self.data.chmod(0o555)
            for command in (["list"], ["find", "task"], ["inspect", tool_id]):
                result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data), *command], text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(json.loads(result.stdout)["ok"])
            self.assertEqual(self.reg.db_path.read_bytes(), before)
        finally:
            self.data.chmod(0o700)
            self.reg.db_path.chmod(0o600)
            lock.chmod(0o600)

    def test_reader_returns_committed_snapshot_while_writer_holds_lock(self):
        previous = self.reg.list()["revision"]
        with self.reg.transaction(write=True) as state:
            state["max_depth"] = 4
            result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data), "list"], text=True, capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["revision"], previous)
        self.assertEqual(self.reg.list()["revision"], previous + 1)

    def test_read_errors_are_not_mistaken_for_an_empty_registry(self):
        self.reg.db_path.write_text("{incomplete", encoding="utf-8")
        with self.assertRaises(registry.RegistryError) as error:
            self.reg.list()
        self.assertEqual(error.exception.code, "registry_corrupt")
        self.assertEqual(self.reg.db_path.read_text(encoding="utf-8"), "{incomplete")
        with mock.patch.object(Path, "lstat", side_effect=PermissionError("access denied")):
            with self.assertRaises(PermissionError):
                self.reg.list()

    def test_atomic_snapshots_remain_valid_during_concurrent_writes(self):
        processes = []
        for index in range(10):
            path = self.project("snapshot-" + str(index))
            card = self.base / ("snapshot-card-" + str(index) + ".json")
            card.write_text(json.dumps({"path": str(path)}), encoding="utf-8")
            processes.append(subprocess.Popen([sys.executable, str(SCRIPT), "--data-dir", str(self.data), "register", "--file", str(card)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        last_revision = 0
        for _ in range(60):
            snapshot = self.reg.list()
            self.assertGreaterEqual(snapshot["revision"], last_revision)
            self.assertEqual(snapshot["revision"], snapshot["total"] + 1)
            self.assertEqual(len(snapshot["tools"]), snapshot["total"])
            last_revision = snapshot["revision"]
        for process in processes:
            out, err = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, err + out)
            self.assertTrue(json.loads(out)["ok"])
        final = self.reg.list()
        self.assertEqual(final["total"], 10)
        self.assertEqual(final["revision"], 11)


if __name__ == "__main__":
    unittest.main()
