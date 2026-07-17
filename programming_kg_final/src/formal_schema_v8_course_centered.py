"""Schema v8: course-centered programming knowledge graph.

The course tree and the cross-course core network are deliberately separated:
``part_of`` never crosses course boundaries, while ``maps_to_core`` is the
only bridge from a course-local teaching node to a shared ``CoreConcept``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import formal_schema_v7 as v7


COURSE_TYPE = "Course"
CORE_CONCEPT_TYPE = "CoreConcept"

CURRICULUM_TYPES = set(v7.CURRICULUM_TYPES)
SPECIALIZED_TEACHING_TYPES = set(v7.SPECIALIZED_TEACHING_TYPES)
TEACHING_TYPES = CURRICULUM_TYPES | SPECIALIZED_TEACHING_TYPES
LOCAL_CORE_CANDIDATE_TYPES = {
    "KnowledgePoint",
    "Algorithm",
    "OperationRule",
    "ComplexityMetric",
    "AlgorithmStrategy",
}

DISPLAY_NAMES = {
    **v7.DISPLAY_NAMES,
    "maps_to_core": "映射到核心概念",
}

RELATION_SCHEMA: dict[str, tuple[set[str], set[str]]] = {
    **v7.RELATION_SCHEMA,
    # A course belongs to the programming-domain root. Course-local domains,
    # units and points may then belong to this Course node.
    "part_of": (TEACHING_TYPES | {COURSE_TYPE}, TEACHING_TYPES | {COURSE_TYPE}),
    # This is intentionally the only local-to-global bridge.
    "maps_to_core": (LOCAL_CORE_CANDIDATE_TYPES, {CORE_CONCEPT_TYPE}),
    # Shared core concepts can preserve curated semantic and prerequisite links.
    "prerequisite_of": (
        (TEACHING_TYPES - {"KnowledgeDomain"}) | {CORE_CONCEPT_TYPE},
        (TEACHING_TYPES - {"KnowledgeDomain"}) | {CORE_CONCEPT_TYPE},
    ),
}


def validate_graph_schema(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    semantic_types: set[str],
) -> dict[str, Any]:
    """Check endpoint types and the course-local/global boundary."""
    violations: list[dict[str, Any]] = []
    for edge in edges:
        relation = str(edge.get("type", ""))
        source = nodes.get(str(edge.get("source", "")))
        target = nodes.get(str(edge.get("target", "")))
        if not source or not target:
            violations.append({"edge_id": edge.get("id", ""), "reason": "relation endpoint is missing"})
            continue

        source_type = str(source.get("type", ""))
        target_type = str(target.get("type", ""))
        schema = RELATION_SCHEMA.get(relation)
        if schema is None and relation in semantic_types:
            schema = (TEACHING_TYPES | {CORE_CONCEPT_TYPE}, TEACHING_TYPES | {CORE_CONCEPT_TYPE})
        if schema is None:
            violations.append({"edge_id": edge.get("id", ""), "relation": relation, "reason": "undefined relation type"})
            continue
        if source_type not in schema[0] or target_type not in schema[1]:
            violations.append(
                {
                    "edge_id": edge.get("id", ""),
                    "relation": relation,
                    "source_type": source_type,
                    "target_type": target_type,
                    "reason": "endpoint types violate schema v8",
                }
            )
            continue

        # A tree edge must stay within one course. The only allowed exception is
        # Course -> ProgrammingDomain root, which has no course_id itself.
        if relation == "part_of":
            source_course = str(source.get("course_id", ""))
            target_course = str(target.get("course_id", ""))
            if source_type == COURSE_TYPE:
                continue
            if not source_course or source_course != target_course:
                violations.append(
                    {
                        "edge_id": edge.get("id", ""),
                        "relation": relation,
                        "reason": "part_of must remain inside one course tree",
                    }
                )
        if relation == "maps_to_core" and target_type != CORE_CONCEPT_TYPE:
            violations.append({"edge_id": edge.get("id", ""), "reason": "maps_to_core target must be CoreConcept"})

    return {
        "valid": not violations,
        "violation_count": len(violations),
        "violation_type_distribution": dict(Counter(item.get("relation", "unknown") for item in violations)),
        "violations": violations[:100],
    }
