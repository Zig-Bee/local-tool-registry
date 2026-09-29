"""Installer integration tests: isolated catalogs, fake Codex and offline downloads."""
import importlib.util
import io
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ltr_setup", REPO / "scripts/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ltr-installer-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "我的 工具 $(touch nope)"
        project = self.root / "blue-seed"
        project.mkdir(parents=True)
        (project / "README.md").write_text("# Blue Seed\n\nA local CSV report tool.\n")
        self.data = self.base / "catalog"
        self.log = self.base / "codex.jsonl"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.codex = self.bin / "codex"
        self.executable(self.codex, '''import json, os, sys
with open(os.environ["LTR_TEST_CODEX_LOG"], "a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("LTR_TEST_CODEX_FAIL") and sys.argv[1:3] == ["plugin", "add"]:
    print("fixture install failure"); sys.exit(7)
print("fixture codex: add marketplace")
''')
        self.archive = self.base / "fixture.tar.gz"
        self.executable(self.bin / "curl", '''import json, os, shutil, sys
with open(os.environ["LTR_TEST_CURL_LOG"], "a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
target = sys.argv[sys.argv.index("--output") + 1]
if os.environ.get("LTR_TEST_CURL_FAIL"):
    open(target, "w").write("partial download"); sys.exit(22)
shutil.copyfile(os.environ["LTR_TEST_ARCHIVE"], target)
''')
        self.env = dict(os.environ, LTR_DATA_DIR=str(self.data),
                        LTR_REPOSITORY="fixture/local-tool-registry", LTR_REF="main",
                        LTR_TEST_CODEX_LOG=str(self.log), LTR_TEST_ARCHIVE=str(self.archive),
                        LTR_TEST_CURL_LOG=str(self.base / "curl.jsonl"),
                        TMPDIR=str(self.base), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.env.pop("XDG_DATA_HOME", None)

    def executable(self, path, body):
        path.write_text("#!" + sys.executable + "\n" + body)
        path.chmod(0o755)

    def invoke(self, args, env=None, script=None):
        return subprocess.run(args, env=env or self.env, cwd=str(self.base),
                              input=script, capture_output=True, text=True, timeout=15)

    def run_setup(self, *args, env=None):
        return self.invoke([sys.executable, str(REPO / "scripts/setup.py"), *args], env=env)

    def make_archive(self, malicious=None):
        with tarfile.open(self.archive, "w:gz") as archive:
            for path in sorted(REPO.rglob("*")):
                rel = path.relative_to(REPO)
                if path.is_file() and not any(x in rel.parts for x in (".git", "__pycache__", "evaluation")):
                    archive.add(path, arcname="local-tool-registry-main/" + rel.as_posix())
            if malicious:
                member = tarfile.TarInfo("local-tool-registry-main/" + malicious)
                member.size = 4
                archive.addfile(member, io.BytesIO(b"oops"))

    def pipe_install(self, *args, env=None):
        return self.invoke(["bash", "-s", "--", *args], env=env, script=(REPO / "install.sh").read_text())

    def test_local_install_spaced_paths_and_no_shell_interpretation(self):
        result = self.invoke(["bash", str(REPO / "install.sh"), "--root", str(self.root)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = json.loads((self.data / "registry.json").read_text())
        self.assertEqual(state["roots"], [str(self.root.resolve())])
        self.assertEqual(len(state["tools"]), 1)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([call for call in calls if call[:1] == ["plugin"]][-1],
                         ["plugin", "add", "local-tool-registry@local-tool-registry"])
        self.assertEqual(calls[-1][-2:], ["app-server", "--stdio"])
        self.assertIn("/hooks", result.stdout)
        self.assertFalse((self.base / "nope").exists())
        self.assertFalse((self.base / "curl.jsonl").exists())

    def test_preview_and_invalid_root_do_not_mutate(self):
        result = self.run_setup("--root", str(self.root), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.data.exists())
        result = self.run_setup("--root", str(self.base / "missing"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.data.exists())

    def test_rerun_reuses_roots_and_append_keeps_records(self):
        self.assertEqual(self.run_setup("--configure-only", "--root", str(self.root)).returncode, 0)
        before = json.loads((self.data / "registry.json").read_text())
        self.assertEqual(self.run_setup("--configure-only", "--non-interactive").returncode, 0)
        extra = self.base / "more tools"
        extra.mkdir()
        result = self.run_setup("--configure-only", "--root", str(extra))
        self.assertEqual(result.returncode, 0, result.stderr)
        after = json.loads((self.data / "registry.json").read_text())
        self.assertEqual(after["roots"], [str(self.root.resolve()), str(extra.resolve())])
        self.assertEqual(set(before["tools"]), set(after["tools"]))

    def test_headless_first_install_needs_root_and_corrupt_data_is_kept(self):
        result = self.run_setup("--non-interactive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--root", result.stderr)
        self.assertFalse(self.log.exists())
        self.data.mkdir()
        (self.data / "registry.json").write_text("broken")
        result = self.run_setup("--root", str(self.root))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual((self.data / "registry.json").read_text(), "broken")
        self.assertFalse(self.log.exists())

    def test_codex_failure_stops_before_catalog_write(self):
        result = self.run_setup("--root", str(self.root), env=dict(self.env, LTR_TEST_CODEX_FAIL="1"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture install failure", result.stderr)
        self.assertFalse((self.data / "registry.json").exists())

    def test_pipe_download_extract_and_configure(self):
        self.make_archive()
        result = self.pipe_install("--root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        sources = list((self.data / "sources").iterdir())
        self.assertEqual(len(sources), 1)
        self.assertTrue((sources[0] / ".agents/plugins/marketplace.json").is_file())
        self.assertTrue((sources[0] / "plugins/local-tool-registry/.codex-plugin/plugin.json").is_file())
        calls = self.log.read_text()
        self.assertIn(str(sources[0]), calls)
        self.assertTrue((self.data / "registry.json").is_file())
        self.assertFalse(list(self.base.glob("ltr-download.*")))

    def test_download_failure_and_traversal_do_not_install(self):
        result = self.pipe_install("--root", str(self.root), env=dict(self.env, LTR_TEST_CURL_FAIL="1"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertFalse(list(self.base.glob("ltr-download.*")))
        self.make_archive("../../escaped.txt")
        result = self.pipe_install("--root", str(self.root))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.data / "escaped.txt").exists())
        self.assertFalse(list((self.data / "sources").iterdir()))

    def test_piped_installer_reads_answers_from_controlling_terminal(self):
        self.make_archive()
        child, master = pty.fork()
        if child == 0:
            command = "cat " + shlex.quote(str(REPO / "install.sh")) + " | bash -s -- --configure-only"
            os.execvpe("bash", ["bash", "-c", command], self.env)
        output = b""
        answered = False
        status = None
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        chunk = b""
                    output += chunk
                    if not answered and "输入编号" in output.decode("utf-8", errors="replace"):
                        os.write(master, (str(self.root) + "\n\n").encode())
                        answered = True
                pid, status_value = os.waitpid(child, os.WNOHANG)
                if pid:
                    status = status_value
                    break
            self.assertIsNotNone(status, output.decode(errors="replace"))
            self.assertEqual(os.WEXITSTATUS(status), 0, output.decode(errors="replace"))
            self.assertTrue(answered)
            state = json.loads((self.data / "registry.json").read_text())
            self.assertEqual(state["roots"], [str(self.root.resolve())])
        finally:
            os.close(master)
            if status is None:
                os.kill(child, signal.SIGKILL)
                os.waitpid(child, 0)

    def test_directory_chooser_and_codex_detection(self):
        answers = io.StringIO("not-a-directory\n" + shlex.quote(str(self.root)) + "\n\n")
        with mock.patch.object(setup, "terminal_input") as terminal:
            terminal.return_value.__enter__.return_value = answers
            self.assertEqual(setup.choose_roots([]), [self.root.resolve()])
        self.assertEqual(setup.find_codex(str(self.codex)), str(self.codex))
        with mock.patch.object(setup.sys, "platform", "darwin"), \
                mock.patch.object(setup.shutil, "which", return_value=None), \
                mock.patch.object(setup.Path, "is_file", side_effect=lambda: True), \
                mock.patch.object(setup.os, "access", return_value=True):
            self.assertEqual(setup.find_codex(), "/Applications/Codex.app/Contents/Resources/codex")


if __name__ == "__main__":
    unittest.main()
