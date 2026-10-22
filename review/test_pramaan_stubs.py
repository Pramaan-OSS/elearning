"""Standalone checks: python3 -m unittest discover -s review -p 'test_*.py'."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "lms" / "pramaan.py"
SPEC = importlib.util.spec_from_file_location("pramaan_stub_boundary", MODULE_PATH)
boundary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = boundary
SPEC.loader.exec_module(boundary)


class FakeTransport:
    """Strict wire-contract fake; no network and no permissive schema bypass."""
    def __init__(self, response=None, status=200):
        self.requests = []
        self.status = status
        self.response = response if response is not None else {}

    def __call__(self, method, url, headers, body):
        if url.endswith(("/llm.chat", "/llm.complete")):
            boundary.generation_request(body, normalise=False)
        self.requests.append((method, url, headers, body))
        return self.status, self.response


def client(transport, **kwargs):
    return boundary.PramaanClient(api_key="fake", transport=transport,
                                  sleep=lambda _: None, **kwargs)
