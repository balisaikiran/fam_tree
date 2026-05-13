import logging
import time
from typing import Dict, Any, Optional
from app.db.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)

def get_person_tree(
    spm_person_no: str, 
    depth: int = 3,
    person_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Enhanced 5-tier tree supporting biological, step, and guardian relationships.
    
    Includes:
      - ego (self)
      - spouses (1 hop via SPOUSE_OF)
      - biological parents & grandparents (up to 2 hops via CHILD_OF)
      - step-parents (via STEP_CHILD_OF)
      - guardians (via GUARDIAN_OF)
      - biological children & grandchildren (up to 2 hops via CHILD_OF)
      - step-children (via STEP_CHILD_OF reverse)
      - biological siblings (share >=1 biological parent via CHILD_OF)
      - step-siblings (children of step-parents)
    
    Emits relationships:
      - CHILD_OF (child -> biological parent, directed)
      - STEP_CHILD_OF (step-child -> step-parent, directed)
      - GUARDIAN_OF (ward -> guardian, directed)
      - SPOUSE_OF (bidirectional, deduplicated)
    
    Args:
        spm_person_no: Root person ID
        depth: Tree depth (capped at 5 tiers: max 2 up, 2 down)
        person_type: Optional filter - 'citizen' or 'resident'
        
    Returns:
        Dict with root, nodes (with full metadata), and edges
    """
    logger.info(
        "graph.get_person_tree.start | id=%s | depth=%d | person_type=%s",
        spm_person_no,
        depth,
        person_type,
    )

    # Cap to 5 tiers: max 2 up, 2 down
    up_hops = min(2, max(0, depth - 1))
    down_hops = min(2, max(0, depth - 1))
    logger.debug(
        "graph.get_person_tree.hops | up=%d | down=%d", up_hops, down_hops
    )
    
    # Build label filter for person_type
    # On-prem data uses labels: Person (citizen) and Resident (may also carry Person)
    if person_type and person_type.lower() == 'citizen':
        label_filter = "AND 'Person' IN labels(ego) AND NOT 'Resident' IN labels(ego)"
    elif person_type and person_type.lower() == 'resident':
        label_filter = "AND 'Resident' IN labels(ego)"
    else:
        label_filter = ""

    cypher = f"""
    MATCH (ego)
    WHERE (ego:Person OR ego:Resident)
      AND ego.spm_person_no = $id
      {label_filter}
    
    WITH ego
    WHERE ego IS NOT NULL

    // === SPOUSES ===
    OPTIONAL MATCH (ego)-[:SPOUSE_OF]-(sp)
    WHERE sp:Person OR sp:Resident
    
    // === BIOLOGICAL FAMILY ===
    // Biological parents & grandparents (up to 2 hops)
    OPTIONAL MATCH (ego)-[:CHILD_OF*1..{up_hops}]->(bio_anc)
    WHERE bio_anc:Person OR bio_anc:Resident
    
    // Biological children & grandchildren (up to 2 hops down)
    OPTIONAL MATCH (ego)<-[:CHILD_OF*1..{down_hops}]-(bio_desc)
    WHERE bio_desc:Person OR bio_desc:Resident
    
    // Biological siblings (share >=1 biological parent)
    OPTIONAL MATCH (ego)-[:CHILD_OF]->(bio_parent)<-[:CHILD_OF]-(bio_sib)
    WHERE (bio_sib:Person OR bio_sib:Resident) AND bio_sib <> ego

    // Direct siblings via explicit SIBLING_OF edge
    OPTIONAL MATCH (ego)-[:SIBLING_OF]-(direct_sib)
    WHERE (direct_sib:Person OR direct_sib:Resident) AND direct_sib <> ego
    
    // === STEP RELATIONSHIPS ===
    // Step-parents (people ego is step-child of)
    OPTIONAL MATCH (ego)-[:STEP_CHILD_OF]->(step_parent)
    WHERE step_parent:Person OR step_parent:Resident
    
    // Step-children (people who are step-children of ego)
    OPTIONAL MATCH (ego)<-[:STEP_CHILD_OF]-(step_child)
    WHERE step_child:Person OR step_child:Resident
    
    // Step-grandparents (step-parents' parents)
    OPTIONAL MATCH (ego)-[:STEP_CHILD_OF]->(step_parent)-[:CHILD_OF]->(step_gp)
    WHERE step_gp:Person OR step_gp:Resident
    
    // Step-siblings (biological children of step-parents)
    // These are people who share a step-parent with ego but are biologically related to that parent
    OPTIONAL MATCH (ego)-[:STEP_CHILD_OF]->(step_parent)<-[:CHILD_OF]-(step_sib)
    WHERE (step_sib:Person OR step_sib:Resident) AND step_sib <> ego
    
    // === GUARDIAN RELATIONSHIPS ===
    // Guardians (people who are guardians of ego)
    OPTIONAL MATCH (ego)-[:GUARDIAN_OF]->(guardian)
    WHERE guardian:Person OR guardian:Resident
    
    // Wards (people ego is guardian of)
    OPTIONAL MATCH (ego)<-[:GUARDIAN_OF]-(ward)
    WHERE ward:Person OR ward:Resident

    WITH ego,
         collect(DISTINCT sp) AS spouses,
         collect(DISTINCT bio_anc) AS bio_ancestors,
         collect(DISTINCT bio_desc) AS bio_descendants,
         collect(DISTINCT bio_sib) AS bio_siblings,
         collect(DISTINCT direct_sib) AS direct_siblings,
         collect(DISTINCT step_parent) AS step_parents,
         collect(DISTINCT step_child) AS step_children,
         collect(DISTINCT step_gp) AS step_grandparents,
         collect(DISTINCT step_sib) AS step_siblings,
         collect(DISTINCT guardian) AS guardians,
         collect(DISTINCT ward) AS wards

    // Combine all nodes, ensuring ego is included
    WITH ego,
         spouses, bio_ancestors, bio_descendants, bio_siblings, direct_siblings,
         step_parents, step_children, step_grandparents, step_siblings,
         guardians, wards,
         [n IN (
             [ego] +
             spouses +
             bio_ancestors + bio_descendants + bio_siblings + direct_siblings +
             step_parents + step_children + step_grandparents + step_siblings +
             guardians + wards
         ) WHERE n IS NOT NULL] AS all_nodes
    
    WITH ego, all_nodes

    // === GET EDGES ===
    // Biological CHILD_OF edges (include parent sex to identify mother)
    UNWIND all_nodes AS child
    OPTIONAL MATCH (child)-[:CHILD_OF]->(parent)
    WHERE parent IN all_nodes
    WITH ego, all_nodes, collect(DISTINCT {{
        source: child.spm_person_no,
        target: parent.spm_person_no,
        type: 'CHILD_OF',
        parent_sex: parent.sex
    }}) AS child_edges

    // STEP_CHILD_OF edges
    UNWIND all_nodes AS step_child
    OPTIONAL MATCH (step_child)-[:STEP_CHILD_OF]->(step_parent)
    WHERE step_parent IN all_nodes
    WITH ego, all_nodes, child_edges, collect(DISTINCT {{
        source: step_child.spm_person_no,
        target: step_parent.spm_person_no,
        type: 'STEP_CHILD_OF'
    }}) AS step_child_edges

    // GUARDIAN_OF edges
    UNWIND all_nodes AS ward
    OPTIONAL MATCH (ward)-[:GUARDIAN_OF]->(guardian)
    WHERE guardian IN all_nodes
    WITH ego, all_nodes, child_edges, step_child_edges, collect(DISTINCT {{
        source: ward.spm_person_no,
        target: guardian.spm_person_no,
        type: 'GUARDIAN_OF'
    }}) AS guardian_edges

    // Direct explicit SIBLING_OF edges
    UNWIND all_nodes AS s1
    OPTIONAL MATCH (s1)-[:SIBLING_OF]-(s2)
    WHERE s2 IN all_nodes AND s1.spm_person_no < s2.spm_person_no
    WITH ego, all_nodes, child_edges, step_child_edges, guardian_edges,
         collect(DISTINCT {{
            source: s1.spm_person_no,
            target: s2.spm_person_no,
            type: 'SIBLING_OF'
         }}) AS direct_sibling_edges

    // Derived sibling edges (share >=1 biological parent via CHILD_OF)
    UNWIND all_nodes AS d1
    OPTIONAL MATCH (d1)-[:CHILD_OF]->(shared_parent)<-[:CHILD_OF]-(d2)
    WHERE d2 IN all_nodes
      AND d1 <> d2
      AND d1.spm_person_no < d2.spm_person_no
    WITH ego, all_nodes, child_edges, step_child_edges, guardian_edges, direct_sibling_edges,
         direct_sibling_edges + collect(DISTINCT {{
            source: d1.spm_person_no,
            target: d2.spm_person_no,
            type: 'SIBLING_OF'
         }}) AS sibling_edges

    // SPOUSE_OF edges (deduplicated, include relationship status if available)
    UNWIND all_nodes AS person1
    OPTIONAL MATCH (person1)-[r:SPOUSE_OF]-(person2)
    WHERE person2 IN all_nodes AND person1.spm_person_no < person2.spm_person_no
    WITH ego, all_nodes, child_edges, step_child_edges, guardian_edges, sibling_edges,
         collect(DISTINCT {{
            source: person1.spm_person_no,
            target: person2.spm_person_no,
            type: 'SPOUSE_OF',
            relationship_status: CASE 
              WHEN r.status = 'inactive' OR r.status = 'divorced' OR r.active = false THEN 'inactive' 
              ELSE 'active' 
            END
         }}) AS spouse_edges

    // Combine all edges
    WITH ego, all_nodes, 
         [e IN child_edges WHERE e.source IS NOT NULL AND e.target IS NOT NULL] +
         [e IN step_child_edges WHERE e.source IS NOT NULL AND e.target IS NOT NULL] +
         [e IN guardian_edges WHERE e.source IS NOT NULL AND e.target IS NOT NULL] +
         [e IN sibling_edges WHERE e.source IS NOT NULL AND e.target IS NOT NULL] +
         [e IN spouse_edges WHERE e.source IS NOT NULL AND e.target IS NOT NULL] AS edges

    // === DETERMINE KINSHIP ===
    // Resolve biological parents for kinship computation
    OPTIONAL MATCH (ego)-[:CHILD_OF]->(bio_father)
    WHERE bio_father IN all_nodes AND bio_father.sex = 'M'
    
    OPTIONAL MATCH (ego)-[:CHILD_OF]->(bio_mother)
    WHERE bio_mother IN all_nodes AND bio_mother.sex = 'F'

    WITH ego, all_nodes, edges, 
         head(collect(DISTINCT bio_father)) AS bio_father, 
         head(collect(DISTINCT bio_mother)) AS bio_mother

    // Build node objects with enhanced kinship
    UNWIND all_nodes AS n
    WITH ego, bio_father, bio_mother, n, edges,
         CASE
           WHEN n = ego THEN 'self'

           // Spouses
           WHEN (n)-[:SPOUSE_OF]-(ego) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'husband'
               WHEN 'F' THEN 'wife'
               ELSE 'spouse'
             END

           // Biological parents
           WHEN (ego)-[:CHILD_OF]->(n) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'father'
               WHEN 'F' THEN 'mother'
               ELSE 'parent'
             END

           // Step-parents
           WHEN (ego)-[:STEP_CHILD_OF]->(n) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'step-father'
               WHEN 'F' THEN 'step-mother'
               ELSE 'step-parent'
             END

           // Guardians
           WHEN (ego)-[:GUARDIAN_OF]->(n) THEN 'guardian'

           // Biological children
           WHEN (n)-[:CHILD_OF]->(ego) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'son'
               WHEN 'F' THEN 'daughter'
               ELSE 'child'
             END

           // Step-children
           WHEN (n)-[:STEP_CHILD_OF]->(ego) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'step-son'
               WHEN 'F' THEN 'step-daughter'
               ELSE 'step-child'
             END

           // Wards
           WHEN (n)-[:GUARDIAN_OF]->(ego) THEN 'ward'

           // Biological siblings (derived via shared parent OR direct SIBLING_OF)
           WHEN (ego)-[:CHILD_OF]->()<-[:CHILD_OF]-(n) OR (ego)-[:SIBLING_OF]-(n) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'brother'
               WHEN 'F' THEN 'sister'
               ELSE 'sibling'
             END

           // Step-siblings (biological children of step-parents)
           WHEN (ego)-[:STEP_CHILD_OF]->()<-[:CHILD_OF]-(n) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'step-brother'
               WHEN 'F' THEN 'step-sister'
               ELSE 'step-sibling'
             END

           // Biological grandparents (paternal)
           WHEN bio_father IS NOT NULL AND (bio_father)-[:CHILD_OF]->(n) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'paternal grandfather'
               WHEN 'F' THEN 'paternal grandmother'
               ELSE 'paternal grandparent'
             END

           // Biological grandparents (maternal)
           WHEN bio_mother IS NOT NULL AND (bio_mother)-[:CHILD_OF]->(n) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'maternal grandfather'
               WHEN 'F' THEN 'maternal grandmother'
               ELSE 'maternal grandparent'
             END

           // Step-grandparents
           WHEN (ego)-[:STEP_CHILD_OF]->()-[:CHILD_OF]->(n) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'step-grandfather'
               WHEN 'F' THEN 'step-grandmother'
               ELSE 'step-grandparent'
             END

           // Biological grandchildren
           WHEN (n)-[:CHILD_OF]->()<-[:CHILD_OF]-(ego) THEN
             CASE toUpper(n.sex)
               WHEN 'M' THEN 'grandson'
               WHEN 'F' THEN 'granddaughter'
               ELSE 'grandchild'
             END

           ELSE ''
         END AS kin

    // Determine person_type from labels (on-prem: Person only = citizen, any with Resident = resident)
    WITH ego, edges, n, kin,
         CASE
           WHEN 'Resident' IN labels(n) THEN 'resident'
           WHEN 'Person' IN labels(n) THEN 'citizen'
           ELSE 'unknown'
         END AS person_type

    WITH ego, edges, collect({{
      id: n.spm_person_no,
      label: coalesce(n.full_name, n.name_eng, n.spm_person_no),
      full_name: coalesce(n.full_name, n.name_eng),
      name_eng: n.name_eng,
      name_arabic: n.name_arabic,
      dob: CASE WHEN n.spm_dob IS NOT NULL THEN toString(n.spm_dob) ELSE null END,
      date_of_birth: CASE WHEN n.spm_dob IS NOT NULL THEN toString(n.spm_dob) ELSE null END,
      unified_id: n.spm_person_no,
      passport_no: n.passport,
      passport: n.passport,
      contact_no: n.contact_no,
      nationality: n.nationality,
      gender: n.sex,
      sex: n.sex,
      national_id: n.national_id,
      person_type: person_type,
      kin: kin
    }}) AS nodes

    RETURN ego.spm_person_no AS root_id, nodes, edges
    """

    started = time.perf_counter()
    rows = neo4j_client.run(cypher, {"id": spm_person_no})
    duration_ms = (time.perf_counter() - started) * 1000

    if not rows or not rows[0]:
        logger.info(
            "graph.get_person_tree.empty | id=%s | duration_ms=%.2f",
            spm_person_no,
            duration_ms,
        )
        return {"root": spm_person_no, "nodes": [], "edges": []}

    rec = rows[0]
    nodes = rec["nodes"] or []
    edges = rec["edges"] or []
    logger.info(
        "graph.get_person_tree.ok | id=%s | nodes=%d | edges=%d | duration_ms=%.2f",
        spm_person_no,
        len(nodes),
        len(edges),
        duration_ms,
    )
    return {
        "root": spm_person_no,
        "nodes": nodes,
        "edges": edges,
    }