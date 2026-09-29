import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_activation.py"
SPEC = importlib.util.spec_from_file_location("ltr_activation", SCRIPT)
activation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activation)

FAKE_SERVER = r'''
import json, os, subprocess, sys, time
from pathlib import Path
base = Path(__file__).parent
plan = json.loads((base / "plan.json").read_text())
(base / "pid").write_text(str(os.getpid()))
(base / "arguments.json").write_text(json.dumps(sys.argv[1:]))
mode = plan.get("mode", "response")
if mode == "hang":
    sys.stdout.write('{"partial":'); sys.stdout.flush()
    sys.stderr.write("secret diagnostic data" * 20000); sys.stderr.flush()
    time.sleep(60)
if mode == "child_holds_pipe":
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    (base / "child_pid").write_text(str(child.pid))
    sys.exit(0)
for line in sys.stdin:
    request = json.loads(line)
    with (base / "requests.jsonl").open("a") as out:
        out.write(json.dumps(request) + "\n")
    method = request["method"]
    if method == "initialize":
        if mode == "initialize_error":
            print(json.dumps({"id": 1, "error": {"message": "sensitive setup error"}}), flush=True)
        else:
            print(json.dumps({"id": 1, "result": {"userAgent": "fixture"}}), flush=True)
    elif method == "initialized":
        pass
    elif method == "hooks/list":
        if mode == "rpc_error":
            reply = {"id": 2, "error": {"message": "private plugin or credential details"}}
        else:
            reply = {"id": 2, "result": {"data": [{"cwd": request["params"]["cwds"][0],
                     "hooks": plan.get("hooks", []), "warnings": [], "errors": plan.get("errors", [])}]}}
        if mode == "oversized":
            sys.stdout.write("x" * (3 * 1024 * 1024)); sys.stdout.flush()
        elif mode == "stderr_noise":
            sys.stderr.write("private diagnostic data" * 20000); sys.stderr.flush()
            print(json.dumps(reply), flush=True)
        elif mode == "split_response":
            raw = json.dumps(reply)
            for i in range(0, len(raw), 13):
                sys.stdout.write(raw[i:i+13]); sys.stdout.flush()
            sys.stdout.write("\n"); sys.stdout.flush()
        elif mode == "invalid_json":
            print("private non-json server output", flush=True)
        else:
            print(json.dumps(reply), flush=True)
    else:
        raise RuntimeError("Unexpected modifying or execution request")
'''


def hooks(trust="trusted", enabled=True):
    return [{"pluginId": "local-tool-registry@fixture-marketplace", "eventName": event,
             "enabled": enabled, "trustStatus": trust, "command": "private command data",
             "sourcePath": "/private/plugin/path"}
            for event in ("sessionStart", "userPromptSubmit")]


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.fake = self.base / "fake-codex"
        self.fake.write_text("#!" + sys.executable + "\n" + FAKE_SERVER)
        self.fake.chmod(0o700)

    def tearDown(self):
        self.temp.cleanup()

    def check(self, fixture_hooks=None, mode="response", timeout=2, errors=None):
        (self.base / "plan.json").write_text(json.dumps({
            "hooks": fixture_hooks or [], "mode": mode, "errors": errors or []}))
        return activation.check_activation(self.fake, self.base, timeout=timeout)

    def assert_process_stopped(self, filename="pid"):
        pid = int((self.base / filename).read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_trusted_hooks_are_ready_and_only_readonly_requests_are_sent(self):
        response = self.check(hooks())
        self.assertEqual(response["status"], "ready")
        requests = [json.loads(line) for line in (self.base / "requests.jsonl").read_text().splitlines()]
        self.assertEqual([request["method"] for request in requests],
                         ["initialize", "initialized", "hooks/list"])
        self.assertEqual(requests[-1]["params"], {"cwds": [str(self.base.resolve())]})
        arguments = json.loads((self.base / "arguments.json").read_text())
        self.assertEqual(arguments[-2:], ["app-server", "--stdio"])
        self.assertNotIn("--dangerously-bypass-hook-trust", arguments)
        scratch = json.loads(arguments[1].split("=", 1)[1])
        self.assertEqual(arguments[3], "log_dir=" + json.dumps(scratch))
        self.assertFalse(Path(scratch).exists())
        self.assertIn("does not prove", response["scope"])
        self.assert_process_stopped()

    def test_untrusted_or_modified_hooks_need_review(self):
        for state in ("untrusted", "modified"):
            with self.subTest(state=state):
                response = self.check(hooks(state))
                self.assertEqual(response["status"], "needs_trust")
                self.assertTrue(all(hook["trustStatus"] == state for hook in response["hooks"]))

    def test_disabled_hooks(self):
        self.assertEqual(self.check(hooks(enabled=False))["status"], "disabled")

    def test_no_hooks_or_missing_required_event_are_not_loaded(self):
        self.assertEqual(self.check()["status"], "not_loaded")
        self.assertEqual(self.check(hooks()[:1])["status"], "not_loaded")

    def test_other_plugins_and_private_fields_are_omitted(self):
        fixture = hooks() + [{"pluginId": "other-plugin@private", "eventName": "private event",
                              "enabled": False, "trustStatus": "untrusted", "secret": "sensitive"}]
        response = self.check(fixture)
        self.assertEqual(response["status"], "ready")
        self.assertEqual(len(response["hooks"]), 2)
        serialized = json.dumps(response)
        for secret in ("private", "sensitive", "command", "sourcePath", "other-plugin"):
            self.assertNotIn(secret, serialized)
        self.assertTrue(all(set(item) == {"event", "enabled", "trustStatus"}
                            for item in response["hooks"]))

    def test_rpc_and_initialization_errors_are_unknown_without_error_details(self):
        for mode in ("rpc_error", "initialize_error", "invalid_json"):
            with self.subTest(mode=mode):
                response = self.check(hooks(), mode=mode)
                self.assertEqual(response["status"], "unknown")
                self.assertNotIn("private", json.dumps(response))
                self.assertNotIn("sensitive", json.dumps(response))

    def test_loading_errors_prevent_ready(self):
        response = self.check(hooks(), errors=[{"path": "/private", "message": "private"}])
        self.assertEqual(response["status"], "unknown")
        self.assertNotIn("private", json.dumps(response))

    def test_partial_lines_and_stderr_noise_do_not_block(self):
        for mode in ("split_response", "stderr_noise"):
            with self.subTest(mode=mode):
                self.assertEqual(self.check(hooks(), mode=mode)["status"], "ready")

    def test_hanging_partial_output_times_out_and_process_is_reaped(self):
        started = time.monotonic()
        response = self.check(hooks(), mode="hang", timeout=1)
        self.assertEqual(response["status"], "unknown")
        self.assertEqual(response["reason"], "timeout")
        self.assertLess(time.monotonic() - started, 2.5)
        self.assert_process_stopped()

    @unittest.skipUnless(os.name == "posix", "POSIX process-group cleanup")
    def test_child_holding_stdout_does_not_block_timeout(self):
        started = time.monotonic()
        response = self.check(mode="child_holds_pipe", timeout=1)
        self.assertEqual(response["status"], "unknown")
        self.assertLess(time.monotonic() - started, 2.5)
        self.assert_process_stopped()
        # Descendants can briefly remain zombies until the OS reaps them; they
        # are killed as part of the diagnostic server's private process group.

    def test_unbounded_output_is_rejected(self):
        response = self.check(hooks(), mode="oversized")
        self.assertEqual(response["status"], "unknown")
        self.assertEqual(response["reason"], "response_too_large")

    def test_missing_or_nonexecutable_binary_is_unknown(self):
        self.assertEqual(activation.check_activation(self.base / "missing", self.base)["status"], "unknown")
        self.fake.chmod(0o600)
        self.assertEqual(activation.check_activation(self.fake, self.base)["status"], "unknown")

    def test_cli_reports_unknown_without_blocking_installer(self):
        completed = subprocess.run([sys.executable, str(SCRIPT), "--codex", str(self.base / "missing"),
                                    "--cwd", str(self.base)], capture_output=True, text=True, timeout=3)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
