"""
Tests for the /healthcheck endpoint.

The path matches bi-dashboards-service so Kubernetes Service definitions and
ingress probes can be configured identically across both. The response body
includes build/patch versions surfaced via env vars.
"""


class TestHealthcheckShape:
    def test_returns_200(self, client):
        r = client.get("/healthcheck")
        assert r.status_code == 200

    def test_payload_has_required_fields(self, client):
        body = client.get("/healthcheck").json()
        # Fields the bi-dashboards healthcheck also returns; keep them in
        # sync so a single probe template can target either service.
        assert body["status"] == "healthy"
        assert "timestamp" in body
        assert "message" in body
        assert "build_version" in body
        assert "patch_version" in body

    def test_no_auth_required(self, client):
        # Probes never carry tokens.
        r = client.get("/healthcheck")
        assert r.status_code == 200

    def test_legacy_health_path_is_404(self, client):
        # The old service exposed /health on port 8000. The new service
        # exposes /healthcheck on 8080. If something is probing /health it
        # should fail loudly so the deployment manifest gets fixed.
        r = client.get("/health")
        assert r.status_code == 404
