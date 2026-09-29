#!/usr/bin/env python3
"""Inspect this plugin's Hook activation without trusting or executing Hooks.

Only initialize, initialized and hooks/list messages are sent. The user's
configuration and plugin cache are read; runtime databases/logs go to a temporary
directory. No thread is started. A failed check never blocks installation.
"""
import argparse
import json
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading
import time


SCOPE = ("Checks enabled and trusted Hook definitions only; does not prove that "
         "Hooks ran in a session or that the agent adopted a tool.")
REQUIRED_EVENTS = {"sessionStart", "userPromptSubmit"}
KNOWN_EVENTS = REQUIRED_EVENTS | {
    "preToolUse", "permissionRequest", "postToolUse", "preCompact", "postCompact",
    "sessionEnd", "subagentStart", "subagentStop", "stop", "interrupt",
}
TRUST_STATES = {"managed", "untrusted", "trusted", "modified"}
MAX_OUTPUT = 2 * 1024 * 1024


def result(status, hooks=None, reason=""):
    return {"status": status, "hooks": hooks or [], "reason": reason, "scope": SCOPE}


def _summarize(response):
    if not isinstance(response, dict) or "error" in response:
        return result("unknown", reason="hooks_list_failed")
    payload = response.get("result")
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        return result("unknown", reason="invalid_hooks_response")
    items = entries[0].get("hooks")
    if not isinstance(items, list):
        return result("unknown", reason="invalid_hooks_response")
    if entries[0].get("errors"):
        return result("unknown", reason="hook_loading_errors")
    hooks = []
    for item in items:
        if not isinstance(item, dict):
            continue
        plugin = item.get("pluginId")
        if not isinstance(plugin, str) or plugin.split("@", 1)[0] != "local-tool-registry":
            continue
        event = item.get("eventName")
        trust = item.get("trustStatus")
        enabled = item.get("enabled")
        hooks.append({"event": event if event in KNOWN_EVENTS else "unknown",
                      "enabled": enabled if isinstance(enabled, bool) else None,
                      "trustStatus": trust if trust in TRUST_STATES else "unknown"})
    hooks.sort(key=lambda hook: (hook["event"], str(hook["enabled"]), hook["trustStatus"]))
    if not hooks:
        return result("not_loaded", reason="plugin_hooks_not_found")
    if any(hook["event"] == "unknown" or hook["enabled"] is None
           or hook["trustStatus"] == "unknown" for hook in hooks):
        return result("unknown", hooks, "incomplete_hook_metadata")
    if not REQUIRED_EVENTS.issubset({hook["event"] for hook in hooks}):
        return result("not_loaded", hooks, "required_hook_missing")
    if any(not hook["enabled"] for hook in hooks):
        return result("disabled", hooks, "plugin_hook_disabled")
    if any(hook["trustStatus"] in {"untrusted", "modified"} for hook in hooks):
        return result("needs_trust", hooks, "review_current_hooks_in_codex")
    return result("ready", hooks, "hook_definitions_enabled_and_trusted")


def _read_output(stream, messages, stopped):
    """Drain bytes independently so partial lines and a full pipe cannot hang us."""
    try:
        while not stopped.is_set():
            chunk = stream.read1(65536)
            while not stopped.is_set():
                try:
                    messages.put(chunk, timeout=0.05)
                    break
                except queue.Full:
                    pass
            if not chunk:
                break
    except (OSError, ValueError):
        pass


def _stop_process(process, stopped, reader):
    stopped.set()
    # This server has its own process group; terminate only processes we started.
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                process.terminate()
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=0.3)
    except subprocess.TimeoutExpired:
        pass
    # A child may still hold stdout after the main process exits.
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    elif process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=0.3)
    except subprocess.TimeoutExpired:
        pass
    reader.join(timeout=0.2)
    process.stdin.close()
    # Avoid waiting on BufferedReader's lock if an inherited pipe remains open.
    if not reader.is_alive():
        process.stdout.close()


def _query(codex, cwd, scratch, timeout):
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            [os.fspath(codex), "-c", "sqlite_home=" + json.dumps(scratch),
             "-c", "log_dir=" + json.dumps(scratch), "app-server", "--stdio"],
            cwd=os.fspath(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=(os.name == "posix"))
    except (OSError, ValueError):
        return result("unknown", reason="app_server_unavailable")
    stopped = threading.Event()
    messages = queue.Queue(maxsize=8)
    reader = threading.Thread(target=_read_output,
                              args=(process.stdout, messages, stopped), daemon=True)
    reader.start()

    def send(message):
        process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        process.stdin.flush()

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "local_tool_registry_activation_check", "version": "1"},
            "capabilities": {"experimentalApi": True}}})
        buffered = b""
        total = 0
        requested = False
        while time.monotonic() < deadline:
            try:
                chunk = messages.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                return result("unknown", reason="timeout")
            if not chunk:
                return result("unknown", reason="app_server_exited")
            total += len(chunk)
            if total > MAX_OUTPUT:
                return result("unknown", reason="response_too_large")
            buffered += chunk
            while b"\n" in buffered:
                line, buffered = buffered.split(b"\n", 1)
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    return result("unknown", reason="invalid_server_output")
                if not isinstance(message, dict):
                    return result("unknown", reason="invalid_server_output")
                if message.get("id") == 1 and not requested:
                    if "error" in message or "result" not in message:
                        return result("unknown", reason="initialization_failed")
                    send({"method": "initialized", "params": {}})
                    send({"id": 2, "method": "hooks/list", "params": {"cwds": [str(cwd)]}})
                    requested = True
                elif message.get("id") == 2 and requested:
                    return _summarize(message)
        return result("unknown", reason="timeout")
    except (OSError, ValueError):
        return result("unknown", reason="app_server_io_error")
    finally:
        _stop_process(process, stopped, reader)


def check_activation(codex, cwd, timeout=8):
    """Return bounded, credential-free status. Never change trust or run a Hook."""
    try:
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            return result("unknown", reason="invalid_timeout")
        cwd = Path(cwd).expanduser().resolve()
        with tempfile.TemporaryDirectory(prefix="local-tool-registry-activation-") as scratch:
            return _query(codex, cwd, scratch, timeout)
    except (OSError, ValueError, TypeError):
        return result("unknown", reason="activation_check_unavailable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--timeout", type=float, default=8)
    args = parser.parse_args()
    print(json.dumps(check_activation(args.codex, args.cwd, args.timeout), ensure_ascii=False))


if __name__ == "__main__":
    main()
