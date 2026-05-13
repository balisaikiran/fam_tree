"""
Tests for /api/v1/family-tree/* and /api/v1/persons/* endpoints.

Every route here is wrapped in Authorization(Group.ICP_FAMILY_TREE_DASHBOARD),
so happy-path tests use `authed_client` (token attached automatically) and the
unauthenticated/unauthorized cases live in test_auth.py.
"""


# ---------------------------------------------------------------------------
# /api/v1/family-tree/search (new in the cleaned backend)
# ---------------------------------------------------------------------------
class TestFamilyTreeSearchValidation:
    def test_missing_value_rejected(self, authed_client, neo4j_stub):
        r = authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "UNIFIED_ID", "value": ""},
        )
        assert r.status_code == 400
        body = r.json()
        # Error envelope shape matches bi-dashboards: {"details": {...}}
        assert body["details"]["code"] == "FAMILY_TREE_VALUE_REQUIRED_001"

    def test_unknown_search_type_rejected(self, authed_client, neo4j_stub):
        r = authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "BIOMETRIC", "value": "abc"},
        )
        assert r.status_code == 400
        assert r.json()["details"]["code"] == "FAMILY_TREE_SEARCH_TYPE_INVALID_001"

    def test_eid_with_no_digits_rejected(self, authed_client, neo4j_stub):
        r = authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "EID", "value": "abc-def-ghij-klm-n"},
        )
        assert r.status_code == 400
        assert r.json()["details"]["code"] == "FAMILY_TREE_EID_NO_DIGITS_001"

    def test_search_type_is_uppercased(self, authed_client, neo4j_stub):
        # The route normalizes searchType to upper, so lowercase should work
        # and the cypher params should be the unmodified value.
        authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "unified_id", "value": "P0020375801"},
        )
        assert neo4j_stub.calls[-1]["params"] == {"val": "P0020375801"}


class TestFamilyTreeSearchUnifiedId:
    def test_not_found_returns_negative_envelope(self, authed_client, neo4j_stub):
        # Default stub returns [] → exists False.
        r = authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "UNIFIED_ID", "value": "P_DOES_NOT_EXIST"},
        )
        assert r.status_code == 200
        assert r.json() == {"exists": False, "personId": None, "person_type": None}

    def test_falsy_first_row_treated_as_not_found(self, authed_client, neo4j_stub):
        neo4j_stub.queue([None])
        r = authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "UNIFIED_ID", "value": "P1"},
        )
        assert r.status_code == 200
        assert r.json()["exists"] is False

    def test_found_citizen(self, authed_client, neo4j_stub):
        neo4j_stub.queue([{"person_id": "P0020375801", "labels": ["Person"]}])
        r = authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "UNIFIED_ID", "value": "P0020375801"},
        )
        assert r.status_code == 200
        assert r.json() == {
            "exists": True,
            "personId": "P0020375801",
            "person_type": "citizen",
        }

    def test_found_resident(self, authed_client, neo4j_stub):
        neo4j_stub.queue([{"person_id": "R5403276", "labels": ["Resident", "Person"]}])
        r = authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "UNIFIED_ID", "value": "R5403276"},
        )
        # Resident label takes precedence per the route logic.
        assert r.json()["person_type"] == "resident"


class TestFamilyTreeSearchEid:
    def test_dashed_eid_normalised_to_digits(self, authed_client, neo4j_stub):
        authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "EID", "value": "784-1990-1234567-8"},
        )
        # Non-digit chars stripped before the cypher param is sent.
        assert neo4j_stub.calls[-1]["params"] == {"val": "784199012345678"}

    def test_already_normalised_eid_passes_through(self, authed_client, neo4j_stub):
        authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "EID", "value": "784199012345678"},
        )
        assert neo4j_stub.calls[-1]["params"] == {"val": "784199012345678"}


class TestFamilyTreeSearchPassport:
    def test_passport_uppercased(self, authed_client, neo4j_stub):
        authed_client.post(
            "/api/v1/family-tree/search",
            json={"searchType": "PASSPORT", "value": "ab12345"},
        )
        assert neo4j_stub.calls[-1]["params"] == {"val": "AB12345"}


# ---------------------------------------------------------------------------
# /api/v1/persons/{id}/exists
# ---------------------------------------------------------------------------
class TestPersonExists:
    def test_returns_false_when_no_rows(self, authed_client, neo4j_stub):
        r = authed_client.get("/api/v1/persons/P999/exists")
        assert r.status_code == 200
        assert r.json() == {"exists": False, "person_type": None}

    def test_returns_false_when_first_row_falsy(self, authed_client, neo4j_stub):
        neo4j_stub.queue([None])
        r = authed_client.get("/api/v1/persons/P999/exists")
        assert r.status_code == 200
        assert r.json() == {"exists": False, "person_type": None}

    def test_classifies_resident_label(self, authed_client, neo4j_stub):
        neo4j_stub.queue([{"labels": ["Resident", "Person"]}])
        r = authed_client.get("/api/v1/persons/R5403276/exists")
        assert r.status_code == 200
        # Resident label takes precedence per the route logic.
        assert r.json() == {"exists": True, "person_type": "resident"}

    def test_classifies_citizen_label(self, authed_client, neo4j_stub):
        neo4j_stub.queue([{"labels": ["Person"]}])
        r = authed_client.get("/api/v1/persons/P0020375801/exists")
        assert r.status_code == 200
        assert r.json() == {"exists": True, "person_type": "citizen"}

    def test_unknown_label_set_returns_exists_with_null_type(self, authed_client, neo4j_stub):
        # Defensive: row exists but neither label is present.
        neo4j_stub.queue([{"labels": ["SomeOtherLabel"]}])
        r = authed_client.get("/api/v1/persons/X1/exists")
        assert r.status_code == 200
        assert r.json() == {"exists": True, "person_type": None}

    def test_passes_id_to_cypher_params(self, authed_client, neo4j_stub):
        authed_client.get("/api/v1/persons/P0020375801/exists")
        assert neo4j_stub.calls[-1]["params"] == {"id": "P0020375801"}


# ---------------------------------------------------------------------------
# /api/v1/persons/{id}/tree
# ---------------------------------------------------------------------------
class TestReadTree:
    def test_returns_empty_tree_when_no_data(self, authed_client, neo4j_stub):
        r = authed_client.get("/api/v1/persons/P1/tree")
        assert r.status_code == 200
        assert r.json() == {"root": "P1", "nodes": [], "edges": []}

    def test_returns_payload_from_graph_service(self, authed_client, neo4j_stub):
        record = {
            "nodes": [
                {"id": "P1", "label": "Ali", "kin": "self"},
                {"id": "P2", "label": "Hassan", "kin": "father"},
            ],
            "edges": [{"source": "P1", "target": "P2", "type": "CHILD_OF"}],
        }
        neo4j_stub.queue([record])

        r = authed_client.get("/api/v1/persons/P1/tree")
        assert r.status_code == 200
        body = r.json()
        assert body["root"] == "P1"
        assert len(body["nodes"]) == 2
        assert body["edges"][0]["type"] == "CHILD_OF"

    def test_default_depth_is_3(self, authed_client, neo4j_stub):
        # depth=3 → up_hops=2, down_hops=2 → "*1..2" appears in cypher
        authed_client.get("/api/v1/persons/P1/tree")
        cypher = neo4j_stub.calls[-1]["cypher"]
        assert "CHILD_OF*1..2" in cypher

    def test_depth_below_minimum_rejected(self, authed_client, neo4j_stub):
        r = authed_client.get("/api/v1/persons/P1/tree?depth=0")
        # FastAPI ge=1 validation fails before route runs → envelope is 422.
        assert r.status_code == 422
        assert "details" in r.json()

    def test_depth_above_maximum_rejected(self, authed_client, neo4j_stub):
        r = authed_client.get("/api/v1/persons/P1/tree?depth=6")
        assert r.status_code == 422

    def test_invalid_person_type_rejected(self, authed_client, neo4j_stub):
        r = authed_client.get("/api/v1/persons/P1/tree?person_type=alien")
        assert r.status_code == 422

    def test_citizen_filter_passed_through(self, authed_client, neo4j_stub):
        authed_client.get("/api/v1/persons/P1/tree?person_type=citizen")
        cypher = neo4j_stub.calls[-1]["cypher"]
        assert "'Person' IN labels(ego)" in cypher
        assert "NOT 'Resident' IN labels(ego)" in cypher

    def test_resident_filter_passed_through(self, authed_client, neo4j_stub):
        authed_client.get("/api/v1/persons/R1/tree?person_type=resident")
        cypher = neo4j_stub.calls[-1]["cypher"]
        assert "'Resident' IN labels(ego)" in cypher
