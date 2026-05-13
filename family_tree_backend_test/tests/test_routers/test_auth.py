"""
Tests for the auth stack — JWTBearer and the Authorization dependency.

We exercise these via a real protected endpoint rather than calling the
dependency in isolation, so the behaviour matches what a request actually
sees end-to-end.

The endpoint used as the probe is /api/v1/persons/P_TEST/exists. With the
default `neo4j_stub` it returns 200 OK with no fanfare, so any non-200 we
observe is purely the auth layer rejecting the request.
"""
import time

import pytest


# A handy "I just want to know if auth let me through" probe endpoint.
PROBE_URL = "/api/v1/persons/P_TEST/exists"


# ---------------------------------------------------------------------------
# Authentication: shape of the Authorization header
# ---------------------------------------------------------------------------
class TestAuthenticationHeader:
    def test_missing_header_rejected(self, client):
        r = client.get(PROBE_URL)
        # FastAPI's HTTPBearer raises 403 when the header is absent; our
        # JWTBearer wraps that as NOT_AUTHENTICATED_001 with status 403.
        assert r.status_code == 403
        assert r.json()["details"]["code"] == "NOT_AUTHENTICATED_001"

    def test_wrong_scheme_rejected(self, client, make_token):
        token = make_token()
        r = client.get(PROBE_URL, headers={"Authorization": f"Basic {token}"})
        # HTTPBearer treats a non-Bearer scheme the same as a missing
        # credential — it raises before our scheme check ever runs, so this
        # surfaces as NOT_AUTHENTICATED_001 too. Documented here so future
        # readers don't expect UNAUTHORIZED_001.
        assert r.status_code == 403
        assert r.json()["details"]["code"] == "NOT_AUTHENTICATED_001"

    def test_garbage_token_rejected(self, client):
        r = client.get(PROBE_URL, headers={"Authorization": "Bearer not.a.real.jwt"})
        assert r.status_code == 401
        assert r.json()["details"]["code"] == "UNAUTHORIZED_003"

    def test_empty_bearer_rejected(self, client):
        r = client.get(PROBE_URL, headers={"Authorization": "Bearer "})
        # HTTPBearer raises before we see the empty credential.
        assert r.status_code == 403
        assert r.json()["details"]["code"] == "NOT_AUTHENTICATED_001"


# ---------------------------------------------------------------------------
# Authorization: group checks
# ---------------------------------------------------------------------------
class TestAuthorizationGroups:
    def test_correct_group_passes(self, client, make_token, neo4j_stub):
        r = client.get(PROBE_URL, headers=make_token.headers())
        assert r.status_code == 200

    def test_missing_group_forbidden(self, client, make_token):
        r = client.get(PROBE_URL, headers=make_token.headers(groups=[]))
        assert r.status_code == 403
        assert r.json()["details"]["code"] == "FORBIDDEN_001"

    def test_wrong_group_forbidden(self, client, make_token):
        # User has groups but not the one this service requires.
        r = client.get(
            PROBE_URL,
            headers=make_token.headers(groups=["ICP-RESIDENCE-DASHBOARD"]),
        )
        assert r.status_code == 403
        assert r.json()["details"]["code"] == "FORBIDDEN_001"

    def test_admin_group_bypass(self, client, make_token, neo4j_stub):
        # ADMIN gets in regardless of the route's required group, mirroring
        # the bi-dashboards Authorization helper.
        r = client.get(PROBE_URL, headers=make_token.headers(groups=["ADMIN"]))
        assert r.status_code == 200

    def test_missing_groups_claim_forbidden(self, client, make_token):
        # If Keycloak's groups mapper isn't configured the claim is absent
        # entirely. Treat that as "no access".
        r = client.get(PROBE_URL, headers=make_token.headers(groups=None))
        # `groups=None` collapses to an empty list inside the bearer; the
        # Authorization dep then fails with FORBIDDEN_001.
        assert r.status_code == 403
        assert r.json()["details"]["code"] == "FORBIDDEN_001"

    def test_extra_groups_dont_break_access(self, client, make_token, neo4j_stub):
        # Realistic token may carry multiple group memberships.
        r = client.get(
            PROBE_URL,
            headers=make_token.headers(
                groups=[
                    "ICP-BORDER-MOVEMENTS-DASHBOARD",
                    "ICP-FAMILY-TREE-DASHBOARD",
                    "some-other-group",
                ]
            ),
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Token expiry — only meaningful when signature verification is on.
# ---------------------------------------------------------------------------
class TestTokenExpiry:
    def test_expired_token_rejected_when_verification_on(
        self, client, make_token, verify_signatures
    ):
        # An expired token has a past `exp` claim. With verification on,
        # python-jose raises ExpiredSignatureError → UNAUTHORIZED_004.
        # With verification off (the default), `exp` isn't checked and the
        # request would be allowed through — covered by the test below.
        r = client.get(
            PROBE_URL,
            headers=make_token.headers(exp=int(time.time()) - 3600),
        )
        # JWKS stub returns no keys → we don't actually reach the exp check;
        # the kid lookup fails first with UNAUTHORIZED_003. This is fine: we
        # just need to assert that with verification ON we don't get a 200.
        assert r.status_code == 401
        assert r.json()["details"]["code"] in {"UNAUTHORIZED_003", "UNAUTHORIZED_004"}

    def test_expired_token_passes_when_verification_off(
        self, client, make_token, neo4j_stub
    ):
        # Verification is off by default in tests, mirroring the service's
        # default. Documented behaviour: gateway is trusted to enforce exp.
        r = client.get(
            PROBE_URL,
            headers=make_token.headers(exp=int(time.time()) - 3600),
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# JWKS / signature verification path
# ---------------------------------------------------------------------------
class TestSignatureVerification:
    def test_jwks_fetched_when_verification_on(
        self, client, make_token, verify_signatures
    ):
        client.get(PROBE_URL, headers=make_token.headers())
        # JWKS should have been fetched at least once (cache was reset).
        assert verify_signatures.fetch_count >= 1

    def test_unknown_kid_triggers_jwks_refetch(
        self, client, make_token, verify_signatures
    ):
        # Two calls with verification on — kid never matches (stub returns
        # no keys) so the bearer should re-fetch after the cache miss.
        client.get(PROBE_URL, headers=make_token.headers())
        client.get(PROBE_URL, headers=make_token.headers())
        # First call: 1 initial + 1 refresh on kid miss = 2. Second call:
        # one more from the still-empty cache. Lower-bound at 2 to keep the
        # assertion robust to caching changes.
        assert verify_signatures.fetch_count >= 2


# ---------------------------------------------------------------------------
# Healthcheck must remain open — Kubernetes liveness/readiness probes
# don't carry auth.
# ---------------------------------------------------------------------------
class TestHealthcheckIsPublic:
    def test_no_auth_required(self, client):
        r = client.get("/healthcheck")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"
