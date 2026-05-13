"""
Shared pytest fixtures.

Two things to make the FastAPI app importable in tests:

1. core.config reads env vars at import time and raises if required ones
   are missing. We set them before importing anything from `app`.
2. Neo4j is stubbed so app startup doesn't try to open a live bolt
   connection.

Auth fixtures are added because every /api/v1/* route sits behind the
Authorization dependency. Tokens are produced by the `make_token` factory and
are *parseable* JWTs (HS256). KEYCLOAK_VERIFY_SIGNATURE is forced off here so
the JWTBearer reads claims without checking the signature — the same posture
this service runs in by default (matches bi-dashboards). A small dedicated
fixture flips verification on for the tests that exercise the JWKS path.
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

# These must be set before any `app` import — config.py reads them at import
# time and exits the process if anything required is missing.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")
os.environ.setdefault("KEYCLOAK_URL", "http://localhost:8080")
os.environ.setdefault("KEYCLOAK_REALM", "icp")
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "icp-frontend")
# Tests run with the same trust-the-gateway posture the service uses in
# production by default. Tests that need to exercise the JWKS path flip this
# on via the `verify_signatures` fixture below.
os.environ.setdefault("KEYCLOAK_VERIFY_SIGNATURE", "false")
# Quiet rate limiter — slowapi shouldn't trip during a short test run anyway,
# but bump it high enough that even a stress test class doesn't 429.
os.environ.setdefault("RATE_LIMIT", "100000")
# Send the rotating file handler somewhere writable on a dev box; the prod
# image uses /app/logs (created in the Dockerfile).
os.environ.setdefault("LOG_DIR", "/tmp/family_tree_test_logs")

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
# Neo4j stub — routes/services under test call neo4j_client.run() and we
# queue the responses up.
# ---------------------------------------------------------------------------
@pytest.fixture
def neo4j_stub(monkeypatch):
    from app.db.neo4j_client import neo4j_client

    queued: List[Any] = []
    calls: List[dict] = []

    def fake_run(cypher, params=None, db=None):
        calls.append({"cypher": cypher, "params": params or {}, "db": db})
        if queued:
            return queued.pop(0)
        return []

    monkeypatch.setattr(neo4j_client, "connect", lambda: None)
    monkeypatch.setattr(neo4j_client, "close", lambda: None)
    monkeypatch.setattr(neo4j_client, "run", fake_run)

    class Stub:
        def queue(self, response):
            queued.append(response)

        @property
        def calls(self):
            return calls

    return Stub()


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def make_token():
    """
    Factory for parseable JWTs. With KEYCLOAK_VERIFY_SIGNATURE=false the bearer
    only inspects the claims, so a token signed with any secret works as long
    as it's a structurally-valid JWT.

    Default claims correspond to a user in the ICP-FAMILY-TREE-DASHBOARD group
    so the typical "happy path" route call needs no overrides:

        client.post(url, headers=make_token.headers())
    """
    from jose import jwt as jose_jwt

    DEFAULT_CLAIMS: Dict[str, Any] = {
        "sub": "user-123",
        "preferred_username": "batman",
        "name": "Batman",
        "email": "batman@example.com",
        "groups": ["ICP-FAMILY-TREE-DASHBOARD"],
        "realm_access": {"roles": ["user"]},
    }

    class Factory:
        def __call__(self, **overrides) -> str:
            claims = {**DEFAULT_CLAIMS, **overrides}
            return jose_jwt.encode(claims, "test-secret", algorithm="HS256")

        def headers(self, **overrides) -> Dict[str, str]:
            return {"Authorization": f"Bearer {self(**overrides)}"}

    return Factory()


@pytest.fixture
def verify_signatures(monkeypatch):
    """
    Flip JWKS verification on for the duration of a test, with a stub JWKS
    fetch so we don't hit the network.
    """
    from app.core.config import config
    from app.middleware import auth_bearer

    monkeypatch.setattr(config, "keycloak_verify_signature", True)

    fetched = {"count": 0}

    def fake_fetch_jwks():
        fetched["count"] += 1
        # Empty key set — every signed-verification path falls through to
        # UNAUTHORIZED_003 when no kid matches.
        return {"keys": []}

    monkeypatch.setattr(auth_bearer, "_fetch_jwks", fake_fetch_jwks)
    monkeypatch.setattr(auth_bearer, "_jwks_cache", None)

    class Handle:
        @property
        def fetch_count(self) -> int:
            return fetched["count"]

    return Handle()


# ---------------------------------------------------------------------------
# Test clients
# ---------------------------------------------------------------------------
@pytest.fixture
def client(neo4j_stub):
    """
    Bare TestClient — for tests that need to control auth headers themselves
    (e.g. asserting on the unauthenticated response).
    """
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed_client(client, make_token):
    """TestClient that injects a valid Authorization header on every request."""
    client.headers.update(make_token.headers())
    return client
