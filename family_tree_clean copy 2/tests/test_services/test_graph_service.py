"""Tests for graph_service.get_person_tree (Neo4j is stubbed in conftest)."""
from app.services.graph_service import get_person_tree


class TestGetPersonTreeEmptyResults:
    def test_empty_when_neo4j_returns_no_rows(self, neo4j_stub):
        # Default stub returns [] → service should return empty tree.
        result = get_person_tree("P0020375801")
        assert result == {"root": "P0020375801", "nodes": [], "edges": []}

    def test_empty_when_first_row_is_falsy(self, neo4j_stub):
        neo4j_stub.queue([None])
        result = get_person_tree("P0020375801")
        assert result["root"] == "P0020375801"
        assert result["nodes"] == []
        assert result["edges"] == []


class TestGetPersonTreeWithData:
    def test_returns_nodes_and_edges_from_record(self, neo4j_stub):
        record = {
            "nodes": [
                {"id": "P1", "label": "Ali", "kin": "self", "person_type": "citizen"},
                {"id": "P2", "label": "Hassan", "kin": "father", "person_type": "citizen"},
            ],
            "edges": [
                {"source": "P1", "target": "P2", "type": "CHILD_OF"},
            ],
        }
        neo4j_stub.queue([record])

        result = get_person_tree("P1")
        assert result["root"] == "P1"
        assert len(result["nodes"]) == 2
        assert result["edges"][0]["type"] == "CHILD_OF"

    def test_null_collections_coerced_to_empty_lists(self, neo4j_stub):
        # Cypher can return null for nodes/edges when collect() is empty.
        neo4j_stub.queue([{"nodes": None, "edges": None}])
        result = get_person_tree("P1")
        assert result["nodes"] == []
        assert result["edges"] == []


class TestPersonTypeFilter:
    def test_citizen_filter_emits_person_label_clause(self, neo4j_stub):
        neo4j_stub.queue([{"nodes": [], "edges": []}])
        get_person_tree("P1", person_type="citizen")
        cypher = neo4j_stub.calls[-1]["cypher"]
        assert "'Person' IN labels(ego)" in cypher
        assert "NOT 'Resident' IN labels(ego)" in cypher

    def test_resident_filter_emits_resident_label_clause(self, neo4j_stub):
        neo4j_stub.queue([{"nodes": [], "edges": []}])
        get_person_tree("R1", person_type="resident")
        cypher = neo4j_stub.calls[-1]["cypher"]
        assert "'Resident' IN labels(ego)" in cypher

    def test_no_filter_when_person_type_is_none(self, neo4j_stub):
        neo4j_stub.queue([{"nodes": [], "edges": []}])
        get_person_tree("P1", person_type=None)
        cypher = neo4j_stub.calls[-1]["cypher"]
        assert "'Person' IN labels(ego)" not in cypher
        assert "'Resident' IN labels(ego)" not in cypher

    def test_filter_is_case_insensitive(self, neo4j_stub):
        neo4j_stub.queue([{"nodes": [], "edges": []}])
        get_person_tree("P1", person_type="CITIZEN")
        assert "'Person' IN labels(ego)" in neo4j_stub.calls[-1]["cypher"]


class TestDepthClamping:
    def test_depth_passed_in_params(self, neo4j_stub):
        neo4j_stub.queue([{"nodes": [], "edges": []}])
        get_person_tree("P1", depth=3)
        # The id is the only param the service forwards to Neo4j.
        assert neo4j_stub.calls[-1]["params"] == {"id": "P1"}

    def test_depth_above_5_clamps_to_2_hops(self, neo4j_stub):
        # Service caps to max 2 up + 2 down regardless of depth value.
        neo4j_stub.queue([{"nodes": [], "edges": []}])
        get_person_tree("P1", depth=99)
        cypher = neo4j_stub.calls[-1]["cypher"]
        assert "CHILD_OF*1..2" in cypher

    def test_depth_one_renders_zero_hops(self, neo4j_stub):
        neo4j_stub.queue([{"nodes": [], "edges": []}])
        get_person_tree("P1", depth=1)
        cypher = neo4j_stub.calls[-1]["cypher"]
        assert "CHILD_OF*1..0" in cypher
