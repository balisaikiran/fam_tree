"""
Tests for the cross-cutting response contract:

- Error envelope shape matches bi-dashboards' — `{"details": {"code", "message", "params"}}`
  so the frontend's response interceptor and route guards work uniformly.
- Validation errors are mapped to the matching ErrorCode (INVALID_INTEGER_001 etc.).
- Security headers are present on every response.
"""


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------
class TestErrorEnvelope:
    def test_http_exception_uses_details_envelope(self, client):
        # Unauthenticated request → 403 with our wrapped envelope.
        body = client.get("/api/v1/persons/P1/exists").json()
        assert set(body.keys()) == {"details"}
        assert set(body["details"].keys()) == {"code", "message", "params"}
        assert body["details"]["code"] == "NOT_AUTHENTICATED_001"
        assert isinstance(body["details"]["params"], list)

    def test_validation_error_uses_details_envelope(self, authed_client):
        # depth=0 fails Query(ge=1) → 422 with our wrapped envelope.
        body = authed_client.get("/api/v1/persons/P1/tree?depth=0").json()
        assert set(body.keys()) == {"details"}
        assert set(body["details"].keys()) == {"code", "message", "params"}

    def test_invalid_integer_mapped_to_invalid_integer_code(self, authed_client):
        body = authed_client.get("/api/v1/persons/P1/tree?depth=banana").json()
        assert body["details"]["code"] == "INVALID_INTEGER_001"
        # The offending input is echoed back in params for the frontend.
        assert body["details"]["params"] == ["banana"]

    def test_pydantic_body_validation_uses_envelope(self, authed_client):
        # Missing required field on the search request body.
        r = authed_client.post("/api/v1/family-tree/search", json={"value": "x"})
        assert r.status_code == 422
        body = r.json()
        assert "details" in body
        assert body["details"]["code"] in {
            "INVALID_INPUT_001",
            "INVALID_INTEGER_001",
            "INVALID_FLOAT_001",
            "INVALID_DATE_001",
            "INVALID_TIME_001",
            "INVALID_DATETIME_001",
        }


# ---------------------------------------------------------------------------
# Security headers — must be present on every response, including errors.
# ---------------------------------------------------------------------------
class TestSecurityHeaders:
    EXPECTED = {
        "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "no-referrer",
    }

    def test_present_on_healthcheck(self, client):
        r = client.get("/healthcheck")
        for k, v in self.EXPECTED.items():
            assert r.headers.get(k) == v

    def test_present_on_authenticated_route(self, authed_client, neo4j_stub):
        r = authed_client.get("/api/v1/persons/P1/exists")
        for k, v in self.EXPECTED.items():
            assert r.headers.get(k) == v

    def test_present_on_error_response(self, client):
        # Unauthenticated → 403; headers must still be set.
        r = client.get("/api/v1/persons/P1/exists")
        assert r.status_code == 403
        for k, v in self.EXPECTED.items():
            assert r.headers.get(k) == v

    def test_x_powered_by_stripped(self, client):
        r = client.get("/healthcheck")
        assert "X-Powered-By" not in r.headers


# ---------------------------------------------------------------------------
# CORS — credentialed + wildcard origin is invalid per spec; verify the
# configured allow_origins value is honoured. Tests run with the default
# ALLOW_ORIGINS="*" set in conftest.
# ---------------------------------------------------------------------------
class TestCors:
    def test_options_preflight_returns_cors_headers(self, client):
        r = client.options(
            "/api/v1/persons/P1/exists",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        # Preflight is handled by CORSMiddleware before any auth dep runs.
        assert r.status_code == 200
        assert "access-control-allow-origin" in {h.lower() for h in r.headers.keys()}
