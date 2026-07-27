"""Entry point so `python3 -m tests` runs the whole suite from the repo root."""

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _load_server_module():
    """Load bws-mcp-server.py as a module.

    The filename has dashes, which isn't a valid Python module identifier,
    so we use importlib to load it under the name `bws_mcp_server`.
    """
    server_path = os.path.join(REPO, "bws-mcp-server.py")
    if "bws_mcp_server" in sys.modules:
        return sys.modules["bws_mcp_server"]
    spec = importlib.util.spec_from_file_location("bws_mcp_server", server_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bws_mcp_server"] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    _load_server_module()
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=HERE,
        pattern="test_*.py",
        top_level_dir=REPO,
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)