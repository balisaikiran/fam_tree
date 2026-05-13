"""
/api/v1/persons/* — person existence + family tree.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.db.neo4j_client import neo4j_client
from app.middleware.authorization import Authorization, Group
from app.services.graph_service import get_person_tree

router = APIRouter(prefix="/api/v1/persons", tags=["persons"])

_auth = Authorization(Group.ICP_FAMILY_TREE_DASHBOARD)


def _classify(labels: list) -> Optional[str]:
    if "Resident" in labels:
        return "resident"
    if "Person" in labels:
        return "citizen"
    return None


@router.get("/{person_id}/exists")
def person_exists(person_id: str, _user: Dict[str, Any] = Depends(_auth)) -> dict:
    cypher = """
    MATCH (p)
    WHERE (p:Person OR p:Resident) AND p.spm_person_no = $id
    RETURN p, labels(p) AS labels
    LIMIT 1
    """
    rows = neo4j_client.run(cypher, {"id": person_id})
    if not rows or not rows[0]:
        return {"exists": False, "person_type": None}

    labels = rows[0].get("labels") or []
    return {"exists": True, "person_type": _classify(labels)}


@router.get("/{person_id}/tree")
def read_tree(
    person_id: str,
    depth: int = Query(3, ge=1, le=5),
    person_type: Optional[str] = Query(None, regex="^(citizen|resident)$"),
    _user: Dict[str, Any] = Depends(_auth),
) -> dict:
    return get_person_tree(person_id, depth=depth, person_type=person_type)
