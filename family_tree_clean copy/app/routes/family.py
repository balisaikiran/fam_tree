"""
Family graph routes.

No internal `/api/v1` prefix — it's applied at include_router in main.py
together with the Authorization dependency, so the auth posture is set in one
place and route paths can be moved without touching the auth wiring.
"""
import re
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.common.errors import ErrorCode, handle_errors
from app.db.neo4j_client import neo4j_client
from app.services.graph_service import get_person_tree
from app.utill.LoggingHandler import LoggingHandler

logger = LoggingHandler.get_logger(__name__)

router = APIRouter()


class FamilyTreeSearchRequest(BaseModel):
    searchType: str
    value: str


def _person_type_from_labels(labels):
    if "Resident" in labels:
        return "resident"
    if "Person" in labels:
        return "citizen"
    return None


@router.post("/family-tree/search")
def family_tree_search(req: FamilyTreeSearchRequest):
    """
    Resolve a person to their canonical Unified ID (spm_person_no) so the
    frontend can then load /persons/{id}/tree.

    Body:
        { "searchType": "UNIFIED_ID" | "EID" | "PASSPORT", "value": "<string>" }

    Returns:
        {
            "exists": bool,
            "personId": "<spm_person_no>" | null,
            "person_type": "citizen" | "resident" | null
        }
    """
    search_type = (req.searchType or "").strip().upper()
    raw_value = (req.value or "").strip()
    logger.info(
        f"family.search.request | search_type={search_type} | value_present={bool(raw_value)}"
    )

    if not raw_value:
        handle_errors(
            error_code=ErrorCode.FAMILY_TREE_VALUE_REQUIRED_001,
            error_context="family.search.validation",
            status_code=400,
        )

    if search_type == "UNIFIED_ID":
        cypher = """
        MATCH (p)
        WHERE (p:Person OR p:Resident) AND p.spm_person_no = $val
        RETURN p.spm_person_no AS person_id, labels(p) AS labels
        LIMIT 1
        """
        params = {"val": raw_value}

    elif search_type == "EID":
        # Frontend accepts either 784-XXXX-XXXXXXX-X or 15 digits — normalize
        # to digits-only on both sides so the comparison is format-agnostic.
        digits = re.sub(r"\D", "", raw_value)
        logger.info(
            f"family.search.normalised | search_type=EID | digit_count={len(digits)}"
        )
        if not digits:
            handle_errors(
                error_code=ErrorCode.FAMILY_TREE_EID_NO_DIGITS_001,
                error_context="family.search.validation",
                status_code=400,
            )
        cypher = """
        MATCH (p)
        WHERE (p:Person OR p:Resident)
          AND p.national_id IS NOT NULL
          AND replace(replace(toString(p.national_id), '-', ''), ' ', '') = $val
        RETURN p.spm_person_no AS person_id, labels(p) AS labels
        LIMIT 1
        """
        params = {"val": digits}

    elif search_type == "PASSPORT":
        cypher = """
        MATCH (p)
        WHERE (p:Person OR p:Resident)
          AND p.passport IS NOT NULL
          AND toUpper(toString(p.passport)) = $val
        RETURN p.spm_person_no AS person_id, labels(p) AS labels
        LIMIT 1
        """
        params = {"val": raw_value.upper()}

    else:
        handle_errors(
            error_code=ErrorCode.FAMILY_TREE_SEARCH_TYPE_INVALID_001,
            error_context="family.search.validation",
            status_code=400,
        )

    rows = neo4j_client.run(cypher, params)
    if not rows or not rows[0] or not rows[0].get("person_id"):
        logger.info(f"family.search.result | search_type={search_type} | exists=False")
        return {"exists": False, "personId": None, "person_type": None}

    person_id = rows[0]["person_id"]
    person_type = _person_type_from_labels(rows[0].get("labels") or [])
    logger.info(
        f"family.search.result | search_type={search_type} | exists=True"
        f" | person_id={person_id} | person_type={person_type}"
    )
    return {
        "exists": True,
        "personId": person_id,
        "person_type": person_type,
    }


@router.get("/persons/{spm_person_no}/exists")
def check_person_exists(spm_person_no: str):
    """
    Check if a person with the given Unified ID exists in the database.

    Returns:
        { "exists": bool, "person_type": "citizen" | "resident" | null }
    """
    logger.info(f"family.exists.lookup | id={spm_person_no}")
    cypher = """
    MATCH (p)
    WHERE (p:Person OR p:Resident) AND p.spm_person_no = $id
    RETURN p, labels(p) AS labels
    LIMIT 1
    """

    rows = neo4j_client.run(cypher, {"id": spm_person_no})

    if not rows or not rows[0]:
        logger.info(f"family.exists.result | id={spm_person_no} | exists=False")
        return {"exists": False, "person_type": None}

    labels = rows[0].get("labels", [])
    person_type = None
    if "Resident" in labels:
        person_type = "resident"
    elif "Person" in labels:
        person_type = "citizen"

    logger.info(
        f"family.exists.result | id={spm_person_no} | exists=True | person_type={person_type}"
    )
    return {"exists": True, "person_type": person_type}


@router.get("/persons/{spm_person_no}/tree")
def read_tree(
    spm_person_no: str,
    depth: int = Query(3, ge=1, le=5),
    person_type: Optional[str] = Query(None, pattern="^(citizen|resident)$"),
):
    """
    Get the family tree for a person, including biological, step, guardian and
    spouse relationships. See graph_service.get_person_tree for the response
    shape.
    """
    logger.info(
        f"family.tree.request | id={spm_person_no} | depth={depth} | person_type={person_type}"
    )
    data = get_person_tree(spm_person_no, depth=depth, person_type=person_type)

    if not data["nodes"]:
        logger.info(f"family.tree.empty | id={spm_person_no}")
        return data

    logger.info(
        f"family.tree.response | id={spm_person_no}"
        f" | nodes={len(data['nodes'])} | edges={len(data['edges'])}"
    )
    return data
