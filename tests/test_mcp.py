"""Exercise the actual stdio MCP wire protocol and its read-only boundaries."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "plugins/local-tool-registry"
SCRIPT = PLUGIN / "scripts/mcp_server.py"
REGISTRY = PLUGIN / "scripts/registry.py"


def request(method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def handshake(version="2025-06-18"):
    return [
        request("initialize", {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1"}}),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]


def call(name="find_local_tools", arguments=None):
    return request("tools/call", {"name": name, "arguments": arguments if arguments is not None else {"query": "extract content from this platform link"}}, 2)


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data = self.base / "catalog"

    def run_mcp(self, messages, raw_prefix=b"", data_dir=None, env=None):
        encoded = raw_prefix + b"".join((json.dumps(message) + "\n").encode() for message in messages)
        argv = [sys.executable, "-B", str(SCRIPT)]
        if data_dir is not False:
            argv.extend(["--data-dir", str(data_dir or self.data)])
        result = subprocess.run(argv, input=encoded, capture_output=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        return [json.loads(line) for line in result.stdout.splitlines()]

    def existing_empty_catalog(self):
        self.data.mkdir()
        state = {"schema_version": 1, "revision": 3, "roots": [], "max_depth": 2, "tools": {}, "ignored_paths": []}
        (self.data / "registry.json").write_text(json.dumps(state), encoding="utf-8")
        return state

    def populated_catalog(self, count=1):
        state = self.existing_empty_catalog()
        project = self.base / "project"
        project.mkdir()
        marker = self.base / "executed"
        (project / "entry.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n")
        for index in range(count):
            tool_id = "tool-example-" + str(index)
            state["tools"][tool_id] = {
                "id": tool_id, "path": str(project), "source": {"registered": True},
                "discovered": {}, "status": "configured", "updated_at": "2020-01-01T00:00:00+00:00",
                "last_seen_at": "2020-01-01T00:00:00+00:00", "evidence": [],
                "overrides": {"name": "Local Reader " + str(index), "description": "Extract content from platform links",
                              "capabilities": ["Extract article text from a link"],
                              "invocation": {"argv": [sys.executable, "entry.py", "{input}"], "cwd": str(project), "required_env": []}},
            }
        (self.data / "registry.json").write_text(json.dumps(state), encoding="utf-8")
        return marker

    def test_handshake_tools_annotations_and_protocol_negotiation(self):
        replies = self.run_mcp(handshake("future-version") + [request("tools/list"), request("ping")])
        self.assertEqual(len(replies), 3)
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        manifest = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(replies[0]["result"]["serverInfo"]["version"], manifest["version"])
        tools = replies[1]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["find_local_tools", "inspect_local_tool"])
        self.assertEqual(tools[0]["inputSchema"]["properties"]["limit"]["default"], 8)
        for tool in tools:
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            self.assertFalse(tool["annotations"]["openWorldHint"])
        self.assertEqual(replies[2]["result"], {})
        self.assertFalse(self.data.exists())

    def test_missing_catalog_is_actionable_error_not_empty_success(self):
        result = self.run_mcp(handshake() + [call()])[-1]["result"]
        self.assertTrue(result["isError"])
        payload = result["structuredContent"]
        self.assertEqual(payload["error"]["code"], "registry_uninitialized")
        self.assertIn("LTR_DATA_DIR", payload["error"]["message"])
        self.assertFalse(payload["search_complete"])
        self.assertFalse(self.data.exists())

    def test_missing_database_in_existing_directory_is_error(self):
        self.data.mkdir()
        result = self.run_mcp(handshake() + [call()])[-1]["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(list(self.data.iterdir()), [])

    def test_existing_empty_catalog_is_success_with_scope(self):
        self.existing_empty_catalog()
        result = self.run_mcp(handshake() + [call()])[-1]["result"]
        self.assertFalse(result["isError"])
        payload = result["structuredContent"]
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["total"], 0)
        self.assertIn("does not establish", payload["selection_note"])
        self.assertEqual(payload["freshness"]["mode"], "cached_metadata")

    def test_find_inspect_and_invocation_are_cached_without_side_effects(self):
        marker = self.populated_catalog()
        before = {str(p.relative_to(self.base)): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.base.rglob("*") if p.is_file()}
        plugin_cache = PLUGIN / "scripts/__pycache__"
        plugin_before = {p.name: p.stat().st_mtime_ns for p in plugin_cache.glob("*")} if plugin_cache.exists() else {}
        messages = handshake() + [call(), call("inspect_local_tool", {"id": "tool-example-0"})]
        replies = self.run_mcp(messages)
        found = replies[1]["result"]["structuredContent"]
        inspected = replies[2]["result"]["structuredContent"]
        self.assertEqual(found["tools"][0], inspected["tool"])
        self.assertTrue(inspected["tool"]["invocation"]["argv"])
        self.assertEqual(inspected["tool"]["updated_at"], "2020-01-01T00:00:00+00:00")
        self.assertFalse(inspected["freshness"]["live_health_check_performed"])
        self.assertFalse(inspected["functional_verification"])
        self.assertTrue(inspected["next_steps"])
        self.assertFalse(marker.exists())
        after = {str(p.relative_to(self.base)): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.base.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        plugin_after = {p.name: p.stat().st_mtime_ns for p in plugin_cache.glob("*")} if plugin_cache.exists() else {}
        self.assertEqual(plugin_before, plugin_after)

    def test_default_eight_and_truncation_can_expand_to_sixty_four(self):
        self.populated_catalog(12)
        replies = self.run_mcp(handshake() + [call(), call(arguments={"query": "link", "limit": 64})])
        short = replies[1]["result"]["structuredContent"]
        full = replies[2]["result"]["structuredContent"]
        self.assertEqual(len(short["tools"]), 8)
        self.assertTrue(short["truncated"])
        self.assertIn("bounded subset", short["selection_note"])
        self.assertEqual(len(full["tools"]), 12)

    def test_unknown_id_corrupt_database_and_symlink_are_tool_errors(self):
        self.existing_empty_catalog()
        result = self.run_mcp(handshake() + [call("inspect_local_tool", {"id": "missing"})])[-1]["result"]
        self.assertEqual(result["structuredContent"]["error"]["code"], "not_found")
        self.assertTrue(result["isError"])
        db = self.data / "registry.json"
        db.write_text("{bad")
        result = self.run_mcp(handshake() + [call()])[-1]["result"]
        self.assertEqual(result["structuredContent"]["error"]["code"], "registry_corrupt")
        self.assertEqual(db.read_text(), "{bad")
        db.unlink()
        db.symlink_to(self.base / "does-not-exist")
        result = self.run_mcp(handshake() + [call()])[-1]["result"]
        self.assertEqual(result["structuredContent"]["error"]["code"], "registry_corrupt")

    def test_invalid_tool_inputs_are_protocol_errors(self):
        invalid = [
            call(arguments={}), call(arguments={"query": " "}), call(arguments={"query": 1}),
            call(arguments={"query": "x" * 16385}), call(arguments={"query": "ok", "limit": True}),
            call(arguments={"query": "ok", "limit": 0}), call(arguments={"query": "ok", "limit": 65}),
            call(arguments={"query": "ok", "limit": 2.2}), call(arguments={"query": "ok", "extra": 1}),
            call("inspect_local_tool", {"id": "../escape"}), call("inspect_local_tool", {}),
            call("inspect_local_tool", {"id": "ok", "extra": 1}), call("unregistered_tool"),
            request("tools/call", {"name": "find_local_tools", "arguments": []}),
        ]
        for reply in self.run_mcp(handshake() + invalid)[1:]:
            self.assertEqual(reply["error"]["code"], -32602)
        self.assertFalse(self.data.exists())

    def test_bad_json_invalid_requests_notifications_and_recovery(self):
        messages = handshake() + [
            {"jsonrpc": "2.0", "method": "notifications/unknown"},
            {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "find_local_tools", "arguments": {"query": "x"}}},
            request("unknown/method"), request("tools/list", []), [],
            {"jsonrpc": "2.0", "id": True, "method": "ping"}, request("ping"),
        ]
        replies = self.run_mcp(messages, b'{broken\n{"id":NaN}\n')
        self.assertEqual([x.get("error", {}).get("code") for x in replies], [-32700, -32700, None, -32601, -32602, -32600, -32600, None])
        self.assertFalse(self.data.exists())

    def test_handshake_required_duplicate_initialize_and_ping(self):
        replies = self.run_mcp([request("ping"), request("tools/list")] + handshake() + [handshake()[0], request("tools/list", {"cursor": "invalid"})])
        self.assertEqual(replies[0]["result"], {})
        self.assertEqual(replies[1]["error"]["code"], -32600)
        self.assertEqual(replies[3]["error"]["code"], -32600)
        self.assertEqual(replies[4]["error"]["code"], -32602)

    def test_oversize_message_is_bounded_and_connection_recovers(self):
        replies = self.run_mcp([request("ping")], b"x" * (1024 * 1024 + 10) + b"\n")
        self.assertEqual(replies[0]["error"]["code"], -32700)
        self.assertEqual(replies[1]["result"], {})

    def test_deep_json_and_malformed_catalog_do_not_crash_server(self):
        replies = self.run_mcp([request("ping")], b"[" * 3000 + b"]" * 3000 + b"\n")
        self.assertEqual(replies[0]["error"]["code"], -32700)
        self.assertEqual(replies[1]["result"], {})
        state = self.existing_empty_catalog()
        state["tools"] = {"invalid-card": None}
        (self.data / "registry.json").write_text(json.dumps(state))
        replies = self.run_mcp(handshake() + [call(), request("ping")])
        self.assertTrue(replies[1]["result"]["isError"])
        self.assertEqual(replies[2]["result"], {})

    def test_shared_data_directory_environment_is_respected(self):
        self.existing_empty_catalog()
        env = dict(os.environ, LTR_DATA_DIR=str(self.data))
        result = self.run_mcp(handshake() + [call()], data_dir=False, env=env)[-1]["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["revision"], 3)

    def test_plugin_mcp_config_resolves_bundled_server(self):
        config = json.loads((PLUGIN / ".mcp.json").read_text())
        entry = config["mcpServers"]["local-tool-registry"]
        self.assertEqual(entry["command"], "python3")
        self.assertIn("-B", entry["args"])
        self.assertEqual(entry["env_vars"], ["LTR_DATA_DIR", "XDG_DATA_HOME"])
        path = entry["args"][-1].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
        self.assertEqual(Path(path), SCRIPT)


if __name__ == "__main__":
    unittest.main()
