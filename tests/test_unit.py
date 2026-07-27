"""Unit tests for argument-validation helpers and small pure utilities.

The server module is loaded via importlib so we can call its private
helpers (prefixed with `_`) directly. Tests are written to fail loudly if
a helper's contract drifts; they don't mock anything because each helper
is a pure function.
"""

import importlib.util
import os
import sys
import unittest

# Bootstrap: load the server module under a normal identifier.
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

VALID_UUID = "11111111-1111-1111-1111-111111111111"


class TestRequireUuid(unittest.TestCase):
    def test_accepts_valid_uuid(self):
        self.assertEqual(bws._require_uuid(VALID_UUID, "secret_id"), VALID_UUID)

    def test_rejects_non_string(self):
        with self.assertRaises(ValueError):
            bws._require_uuid(12345, "secret_id")

    def test_rejects_malformed_uuid(self):
        with self.assertRaises(ValueError):
            bws._require_uuid("not-a-uuid", "secret_id")
        with self.assertRaises(ValueError):
            bws._require_uuid("11111111-1111-1111-1111-11111111111", "secret_id")  # 11 chars short
        with self.assertRaises(ValueError):
            bws._require_uuid("11111111-1111-1111-1111-1111111111111", "secret_id")  # 13 chars long

    def test_rejects_empty_string(self):
        with self.assertRaises(ValueError):
            bws._require_uuid("", "secret_id")


class TestOptionalUuid(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(bws._optional_uuid(None, "project_id"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(bws._optional_uuid("", "project_id"))

    def test_valid_uuid_returns_value(self):
        self.assertEqual(bws._optional_uuid(VALID_UUID, "project_id"), VALID_UUID)

    def test_invalid_uuid_raises(self):
        with self.assertRaises(ValueError):
            bws._optional_uuid("not-a-uuid", "project_id")


class TestOutputFormat(unittest.TestCase):
    def test_none_returns_default(self):
        self.assertEqual(bws._output_format(None), "json")

    def test_default_override(self):
        self.assertEqual(bws._output_format(None, default="yaml"), "yaml")

    def test_valid_format_passes_through(self):
        for fmt in ("json", "yaml", "env", "table", "tsv", "none"):
            self.assertEqual(bws._output_format(fmt), fmt)

    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError):
            bws._output_format("xml")
        with self.assertRaises(ValueError):
            bws._output_format("JSON")  # case-sensitive

    def test_non_string_raises(self):
        with self.assertRaises(ValueError):
            bws._output_format(123)


class TestBool(unittest.TestCase):
    def test_bool_passes_through(self):
        self.assertTrue(bws._bool(True, "flag"))
        self.assertFalse(bws._bool(False, "flag"))

    def test_string_truthy_values(self):
        for v in ("true", "True", "TRUE", "1", "yes", "YES"):
            self.assertTrue(bws._bool(v, "flag"))

    def test_string_falsy_values(self):
        for v in ("false", "False", "FALSE", "0", "no", "NO"):
            self.assertFalse(bws._bool(v, "flag"))

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            bws._bool("maybe", "flag")
        with self.assertRaises(ValueError):
            bws._bool(2, "flag")


class TestString(unittest.TestCase):
    def test_string_passes_through(self):
        self.assertEqual(bws._string("hello", "field"), "hello")

    def test_non_string_raises(self):
        with self.assertRaises(ValueError):
            bws._string(123, "field")
        with self.assertRaises(ValueError):
            bws._string(None, "field")
        with self.assertRaises(ValueError):
            bws._string(["x"], "field")

    def test_max_length_default(self):
        # Default max_len=4096.
        with self.assertRaises(ValueError):
            bws._string("a" * 4097, "field")

    def test_max_length_override(self):
        self.assertEqual(bws._string("abc", "field", max_len=3), "abc")
        with self.assertRaises(ValueError):
            bws._string("abcd", "field", max_len=3)


class TestCommandList(unittest.TestCase):
    def test_valid_argv_passes(self):
        self.assertEqual(bws._command_list(["echo", "hello"]), ["echo", "hello"])

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            bws._command_list([])

    def test_non_list_raises(self):
        with self.assertRaises(ValueError):
            bws._command_list("echo hello")
        with self.assertRaises(ValueError):
            bws._command_list(None)

    def test_non_string_element_raises(self):
        with self.assertRaises(ValueError):
            bws._command_list(["echo", 123])

    def test_empty_string_element_raises(self):
        with self.assertRaises(ValueError):
            bws._command_list(["echo", ""])

    def test_oversize_element_raises(self):
        with self.assertRaises(ValueError):
            bws._command_list(["echo", "x" * 4097])


class TestRequireUuidList(unittest.TestCase):
    UUID_A = "11111111-1111-1111-1111-111111111111"
    UUID_B = "22222222-2222-2222-2222-222222222222"

    def test_valid_list_passes(self):
        self.assertEqual(bws._require_uuid_list([self.UUID_A], "ids"), [self.UUID_A])
        self.assertEqual(
            bws._require_uuid_list([self.UUID_A, self.UUID_B], "ids"),
            [self.UUID_A, self.UUID_B],
        )

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            bws._require_uuid_list([], "ids")

    def test_non_list_raises(self):
        with self.assertRaises(ValueError):
            bws._require_uuid_list("not-a-list", "ids")
        with self.assertRaises(ValueError):
            bws._require_uuid_list(None, "ids")

    def test_invalid_element_raises(self):
        with self.assertRaises(ValueError):
            bws._require_uuid_list(["not-a-uuid"], "ids")
        with self.assertRaises(ValueError):
            bws._require_uuid_list([self.UUID_A, "bad"], "ids")

    def test_error_message_includes_index(self):
        # Verify the error mentions the bad index so the user can locate it.
        with self.assertRaisesRegex(ValueError, r"ids\[1\]"):
            bws._require_uuid_list([self.UUID_A, "bad"], "ids")


class TestAtLeastOne(unittest.TestCase):
    def test_one_present_passes(self):
        bws._at_least_one({"key": "k"}, ["key", "value"])  # should not raise

    def test_multiple_present_passes(self):
        bws._at_least_one({"key": "k", "value": "v"}, ["key", "value"])

    def test_none_present_raises(self):
        with self.assertRaises(ValueError):
            bws._at_least_one({}, ["key", "value"])

    def test_all_none_or_empty_raises(self):
        with self.assertRaises(ValueError):
            bws._at_least_one({"key": None, "value": ""}, ["key", "value"])

    def test_extra_fields_ignored(self):
        bws._at_least_one({"key": "k", "extra": "ignored"}, ["key", "value"])


class TestTryParseJson(unittest.TestCase):
    def test_valid_json_object(self):
        self.assertEqual(bws._try_parse_json('{"a": 1}'), {"a": 1})

    def test_valid_json_array(self):
        self.assertEqual(bws._try_parse_json("[1, 2, 3]"), [1, 2, 3])

    def test_valid_json_string(self):
        self.assertEqual(bws._try_parse_json('"hello"'), "hello")

    def test_invalid_json_returns_none(self):
        self.assertIsNone(bws._try_parse_json("not json"))
        self.assertIsNone(bws._try_parse_json("{unclosed"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(bws._try_parse_json(""))

    def test_garbage_returns_none(self):
        self.assertIsNone(bws._try_parse_json("\x00\x01\x02"))


class TestProtocolConstants(unittest.TestCase):
    """Sanity-check the wire-protocol constants against the MCP spec values."""

    def test_protocol_version_is_current(self):
        # The MCP spec evolves; we pin the announced version. If you bump
        # the protocol version, update this assertion to match.
        self.assertEqual(bws.PROTOCOL_VERSION, "2025-06-18")

    def test_error_codes_match_json_rpc_2_0(self):
        self.assertEqual(bws.PARSE_ERROR, -32700)
        self.assertEqual(bws.INVALID_REQUEST, -32600)
        self.assertEqual(bws.METHOD_NOT_FOUND, -32601)
        self.assertEqual(bws.INVALID_PARAMS, -32602)
        self.assertEqual(bws.INTERNAL_ERROR, -32603)

    def test_supported_output_formats(self):
        self.assertEqual(
            bws.OUTPUT_FORMATS,
            {"json", "yaml", "env", "table", "tsv", "none"},
        )


class TestVersionConstantsMatch(unittest.TestCase):
    """pyproject.toml and SERVER_VERSION must agree. Drift here means
    consumers see one version while uv-managed tooling sees another —
    we hit exactly this bug in v1.5.0/v1.6.0. Use scripts/bump-version.sh
    to update both in lockstep."""

    def _pyproject_version(self):
        # tomllib is stdlib in 3.11+. Fall back to a regex for 3.10.
        import re
        try:
            import tomllib  # type: ignore[import]
            with open("pyproject.toml", "rb") as fh:
                return tomllib.load(fh)["project"]["version"]
        except ImportError:
            text = open("pyproject.toml").read()
            m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
            self.assertIsNotNone(m, "could not find version = in pyproject.toml")
            return m.group(1)

    def _server_version(self):
        import re
        text = open("bws-mcp-server.py").read()
        m = re.search(r'^SERVER_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(m, "could not find SERVER_VERSION = in bws-mcp-server.py")
        return m.group(1)

    def test_pyproject_matches_server_version(self):
        self.assertEqual(self._pyproject_version(), self._server_version())

    def test_versions_are_semver(self):
        import re
        for label, version in (
            ("pyproject.toml", self._pyproject_version()),
            ("SERVER_VERSION", self._server_version()),
        ):
            with self.subTest(source=label):
                self.assertRegex(
                    version,
                    r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$",
                    f"{label} version {version!r} is not semver",
                )


if __name__ == "__main__":
    unittest.main()