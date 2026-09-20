"""Test harness: a fixed TEST-ONLY API secret and a default full-scope token for TestClient.

The secret below exists only inside the test process; it is not a real credential.
Tests that exercise authentication pass ``headers={}`` (or their own) explicitly.
"""

import os

TEST_SECRET = "test-only-secret-" + "x" * 32
os.environ["PLANREVIEW_API_SECRET"] = TEST_SECRET
os.environ.pop("PLANREVIEW_INSECURE_NO_AUTH", None)
os.environ["PLANREVIEW_ENCRYPT_AT_REST"] = "0"  # legacy tests read plan artifacts directly; test_vault.py turns it on
os.environ.update({"PLANREVIEW_RATE_READ": "0", "PLANREVIEW_RATE_WRITE": "0", "PLANREVIEW_RATE_IP": "0"})

import starlette.testclient as _tc  # noqa: E402

from engine import auth  # noqa: E402

SECRET = TEST_SECRET.encode()


def token(scopes=("read", "write", "evidence"), ttl=3600, now=None):
    return auth.mint(SECRET, scopes, ttl, now=now)


_orig_init = _tc.TestClient.__init__


def _init(self, *args, **kwargs):
    if "headers" not in kwargs:
        kwargs["headers"] = {"Authorization": "Bearer " + token()}
    _orig_init(self, *args, **kwargs)


_tc.TestClient.__init__ = _init
