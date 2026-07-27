"""Dispatch and TOOLS/TOOL_DISPATCH invariant tests.

Verifies:
- TOOLS and TOOL_DISPATCH stay in sync (every entry in one is in the other).
- Every tool's inputSchema declares `additionalProperties: False`.
- Every metadata + write tool declares `outputSchema`.
- handle_message returns the right JSON-RPC error codes for the wrong
  inputs (unknown method, unknown tool, invalid args).
- Write-tool gate behavior: write tools return isError=true when
  BWS_MCP_ALLOW_WRITES is unset.
"""

import importlib.util
import json
import os
import sys
import unittest

# Bootstrap: load the server module.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if "bws_mcp_server" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "bws_mcp_server", os.path.join(REPO, "bws-mcp-server.py")
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["bws_mcp_server"] = _module
    _spec.loader.exec_module(_module)
import bws_mcp_server as bws  # noqa: E402

# Some tokens used across the tests.
FAKE_TOKEN = "0.00000000-0000-0000-0000-000000000000"
VALID_PROJECT = "33333333-3333-3333-3333-333333333333"
VALID_SECRET = "11111111-1111-1111-1111-111111111111"


def _result(resp):
    """Helper: assert resp is a success-shaped JSON-RPC message."""
    assert resp is not None, "expected a response, got None (notification?)"
    assert "jsonrpc" in resp and resp["jsonrpc"] == "2.0"
    assert "id" in resp
    return resp


class TestToolsDispatchInvariant(unittest.TestCase):
    """Every TOOLS entry must be wired into TOOL_DISPATCH and vice versa."""

    def test_tools_and_dispatch_in_sync(self):
        tools_names = {t["name"] for t in bws.TOOLS}
        dispatch_names = set(bws.TOOL_DISPATCH.keys())
        self.assertEqual(
            tools_names - dispatch_names,
            set(),
            f"TOOLS has entries not in TOOL_DISPATCH: {tools_names - dispatch_names}",
        )
        self.assertEqual(
            dispatch_names - tools_names,
            set(),
            f"TOOL_DISPATCH has entries not in TOOLS: {dispatch_names - tools_names}",
        )

    def test_tool_count(self):
        # If you add or remove a tool, update this assertion deliberately.
        self.assertEqual(len(bws.TOOLS), 11)

    def test_all_tool_names_unique(self):
        names = [t["name"] for t in bws.TOOLS]
        self.assertEqual(len(names), len(set(names)), "duplicate tool names in TOOLS")


class TestToolSchemaInvariants(unittest.TestCase):
    """Every tool's schema must be well-formed and gated correctly."""

    METADATA_TOOLS = {
        "bws_secret_list",
        "bws_secret_get",
        "bws_project_list",
        "bws_project_get",
    }
    WRITE_TOOLS = {
        "bws_secret_create",
        "bws_secret_edit",
        "bws_secret_delete",
        "bws_project_create",
        "bws_project_edit",
        "bws_project_delete",
    }

    def _by_name(self):
        return {t["name"]: t for t in bws.TOOLS}

    def test_every_tool_has_input_schema(self):
        for tool in bws.TOOLS:
            self.assertIn(
                "inputSchema",
                tool,
                f"{tool['name']} missing inputSchema",
            )
            self.assertEqual(tool["inputSchema"].get("type"), "object")

    def test_every_input_schema_disallows_additional_properties(self):
        for tool in bws.TOOLS:
            schema = tool["inputSchema"]
            self.assertIs(
                schema.get("additionalProperties"),
                False,
                f"{tool['name']}.inputSchema.additionalProperties must be False, got {schema.get('additionalProperties')!r}",
            )

    def test_metadata_and_write_tools_declare_output_schema(self):
        by_name = self._by_name()
        for name in self.METADATA_TOOLS | self.WRITE_TOOLS:
            self.assertIn(
                "outputSchema",
                by_name[name],
                f"{name} should declare outputSchema",
            )
            self.assertEqual(by_name[name]["outputSchema"].get("type"), "object")

    def test_bws_run_does_not_declare_output_schema(self):
        # bws_run is intentionally content-only (stdout/stderr text + a
        # few typed fields); no clean structured representation.
        by_name = self._by_name()
        self.assertNotIn("outputSchema", by_name["bws_run"])

    def test_every_tool_has_title(self):
        for tool in bws.TOOLS:
            self.assertIn(
                "title",
                tool,
                f"{tool['name']} missing title (added per MCP 2025-06-18)",
            )

    def test_every_tool_has_annotations(self):
        for tool in bws.TOOLS:
            self.assertIn(
                "annotations",
                tool,
                f"{tool['name']} missing annotations",
            )
            ann = tool["annotations"]
            # Per MCP spec, every annotations object has readOnlyHint.
            self.assertIn("readOnlyHint", ann)

    def test_write_tools_are_marked_read_only_false(self):
        by_name = self._by_name()
        for name in self.WRITE_TOOLS:
            self.assertIs(
                by_name[name]["annotations"]["readOnlyHint"],
                False,
                f"{name} annotations.readOnlyHint must be False",
            )

    def test_metadata_tools_are_marked_read_only_true(self):
        by_name = self._by_name()
        for name in self.METADATA_TOOLS:
            self.assertIs(
                by_name[name]["annotations"]["readOnlyHint"],
                True,
                f"{name} annotations.readOnlyHint must be True",
            )

    def test_write_tools_listed_in_write_tools_set(self):
        # This invariant ensures the BWS_MCP_ALLOW_WRITES gate actually
        # covers all write tools — if a new write tool is added without
        # updating _WRITE_TOOLS, this test catches it.
        self.assertEqual(set(bws._WRITE_TOOLS), self.WRITE_TOOLS)

    def test_structured_tools_set_consistent(self):
        # _STRUCTURED_OUTPUT_TOOLS should equal metadata ∪ write (all
        # tools that emit structuredContent); bws_run is the only one
        # excluded.
        all_structured = self.METADATA_TOOLS | self.WRITE_TOOLS
        self.assertEqual(set(bws._STRUCTURED_OUTPUT_TOOLS), all_structured)


class TestHandleMessageProtocol(unittest.TestCase):
    """JSON-RPC plumbing tests against handle_message directly."""

    def _initialize(self, msg_id=1):
        return _result(bws.handle_message({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0.0"},
            },
        }, FAKE_TOKEN))

    def test_initialize_returns_protocol_version(self):
        resp = self._initialize()
        self.assertEqual(resp["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(resp["result"]["serverInfo"]["name"], "bws-mcp-server")

    def test_unknown_method_returns_method_not_found(self):
        resp = _result(bws.handle_message({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/destroy",
            "params": {},
        }, FAKE_TOKEN))
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], bws.METHOD_NOT_FOUND)

    def test_unknown_tool_returns_method_not_found(self):
        resp = _result(bws.handle_message({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "bws_nonexistent", "arguments": {}},
        }, FAKE_TOKEN))
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], bws.METHOD_NOT_FOUND)

    def test_ping_returns_empty_result(self):
        resp = _result(bws.handle_message({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "ping",
        }, FAKE_TOKEN))
        self.assertEqual(resp["result"], {})

    def test_tools_list_returns_all_tools(self):
        resp = _result(bws.handle_message({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/list",
        }, FAKE_TOKEN))
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("bws_secret_list", names)
        self.assertIn("bws_run", names)
        # Every returned tool must declare inputSchema.
        for t in resp["result"]["tools"]:
            self.assertIn("inputSchema", t)
            self.assertIs(t["inputSchema"].get("additionalProperties"), False)

    def test_notification_returns_none(self):
        # notifications/initialized should be a notification (no id) and
        # therefore return None from handle_message.
        resp = bws.handle_message({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }, FAKE_TOKEN)
        self.assertIsNone(resp)

    def test_cancelled_notification_returns_none(self):
        resp = bws.handle_message({
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 99, "reason": "test"},
        }, FAKE_TOKEN)
        self.assertIsNone(resp)


class TestToolCallValidation(unittest.TestCase):
    """Tools/call argument validation errors come back as tool errors
    (isError=True), NOT JSON-RPC errors, so the LLM can self-correct."""

    def _call(self, name, arguments):
        return _result(bws.handle_message({
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }, FAKE_TOKEN))

    def test_missing_required_arg_returns_tool_error(self):
        # bws_secret_get requires `secret_id`.
        resp = self._call("bws_secret_get", {})
        self.assertIn("result", resp)
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("invalid arguments", resp["result"]["content"][0]["text"])

    def test_malformed_uuid_returns_tool_error(self):
        resp = self._call("bws_secret_get", {"secret_id": "not-a-uuid"})
        self.assertTrue(resp["result"]["isError"])

    def test_invalid_output_format_returns_tool_error(self):
        resp = self._call("bws_secret_list", {"output": "xml"})
        self.assertTrue(resp["result"]["isError"])

    def test_unknown_tool_returns_jsonrpc_error(self):
        # Unknown tool is a JSON-RPC error, not a tool error — different
        # failure mode than arg validation.
        resp = self._call("bws_nonexistent", {})
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], bws.METHOD_NOT_FOUND)


class TestWriteToolGate(unittest.TestCase):
    """Write tools are gated by BWS_MCP_ALLOW_WRITES in the server env."""

    WRITE_TOOLS = {
        "bws_secret_create": {"key": "k", "value": "v", "project_id": VALID_PROJECT},
        "bws_secret_edit": {"secret_id": VALID_SECRET, "value": "new"},
        "bws_secret_delete": {"secret_ids": [VALID_SECRET]},
        "bws_project_create": {"name": "x"},
        "bws_project_edit": {"project_id": VALID_PROJECT, "name": "renamed"},
        "bws_project_delete": {"project_ids": [VALID_PROJECT]},
    }

    def _call(self, name, arguments, allow_writes=None):
        # Save and restore BWS_MCP_ALLOW_WRITES so the test is hermetic.
        saved = os.environ.get("BWS_MCP_ALLOW_WRITES")
        try:
            if allow_writes is None:
                os.environ.pop("BWS_MCP_ALLOW_WRITES", None)
            else:
                os.environ["BWS_MCP_ALLOW_WRITES"] = allow_writes
            return _result(bws.handle_message({
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }, FAKE_TOKEN))
        finally:
            if saved is None:
                os.environ.pop("BWS_MCP_ALLOW_WRITES", None)
            else:
                os.environ["BWS_MCP_ALLOW_WRITES"] = saved

    def test_write_tool_refused_when_gate_closed(self):
        for name, args in self.WRITE_TOOLS.items():
            with self.subTest(tool=name):
                resp = self._call(name, args, allow_writes=None)
                self.assertTrue(
                    resp["result"]["isError"],
                    f"{name} should return isError when gate is closed",
                )
                text = resp["result"]["content"][0]["text"]
                self.assertIn(
                    "BWS_MCP_ALLOW_WRITES",
                    text,
                    f"{name} error message should mention BWS_MCP_ALLOW_WRITES",
                )

    def test_metadata_tools_unaffected_by_gate(self):
        # Metadata calls should succeed (or fail for *other* reasons like
        # network/token) regardless of BWS_MCP_ALLOW_WRITES.
        # We don't actually need a working token here — we just verify
        # the gate doesn't short-circuit metadata tools. We use a tool
        # arg validation that always fails, and check the error is
        # about *args*, not about the gate.
        resp = self._call("bws_secret_list", {"output": "xml"}, allow_writes=None)
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("output must be one of", resp["result"]["content"][0]["text"])
        self.assertNotIn("BWS_MCP_ALLOW_WRITES", resp["result"]["content"][0]["text"])


class TestStructuredContentEmission(unittest.TestCase):
    """handle_message emits structuredContent for metadata + write tools."""

    METADATA_TOOLS_WITH_DATA = {"bws_secret_list", "bws_project_list"}

    def _call(self, name, arguments):
        return _result(bws.handle_message({
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }, FAKE_TOKEN))

    def test_metadata_tools_have_structured_output_tools_entry(self):
        # Sanity: every metadata tool is in _STRUCTURED_OUTPUT_TOOLS.
        for name in self.METADATA_TOOLS_WITH_DATA:
            self.assertIn(name, bws._STRUCTURED_OUTPUT_TOOLS)

    def test_bws_run_not_in_structured_output_tools(self):
        self.assertNotIn("bws_run", bws._STRUCTURED_OUTPUT_TOOLS)


class TestWireFraming(unittest.TestCase):
    """The server reads and writes Content-Length framed messages."""

    def test_encode_message_uses_newline_delimited_framing(self):
        payload = {"jsonrpc": "2.0", "id": 1, "result": {}}
        encoded = bws._encode_message(payload)
        # Trailing \n so rmcp-style line readers see a complete message.
        self.assertTrue(encoded.endswith(b"\n"))
        # No embedded newlines in the body — would break line-delimited readers.
        body = encoded.rstrip(b"\n")
        self.assertNotIn(b"\n", body)
        # Body is valid JSON.
        self.assertEqual(json.loads(body), payload)

    def test_encode_message_handles_unicode(self):
        # ensure_ascii=False in dumps means non-ASCII payloads survive.
        encoded = bws._encode_message({"jsonrpc": "2.0", "id": 1, "result": {"msg": "héllo"}})
        self.assertIn("héllo".encode("utf-8"), encoded)
        # And the trailing \n is preserved.
        self.assertTrue(encoded.endswith(b"\n"))

    def test_read_message_handles_newline_framing(self):
        import io

        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode("utf-8") + b"\n"
        stream = io.BytesIO(body)
        msg = bws._read_message(stream)
        self.assertEqual(msg, {"jsonrpc": "2.0", "id": 1, "result": {}})

    def test_read_message_handles_lenient_bare_json(self):
        import io

        # Lenient mode for ad-hoc clients: bare JSON without trailing \n
        # still parses (the EOF closes the message).
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8")
        stream = io.BytesIO(body)
        msg = bws._read_message(stream)
        self.assertEqual(msg, {"jsonrpc": "2.0", "id": 1, "method": "ping"})


if __name__ == "__main__":
    unittest.main()