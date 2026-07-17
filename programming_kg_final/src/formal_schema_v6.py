"""Formal programming knowledge graph schema v6.

v6 keeps the v5 curriculum hierarchy and adds three cross-course teaching
concept types.  The module is intentionally separate from v5 so migration can
be audited before any production graph or Neo4j data is replaced.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import formal_schema_v5 as v5


CURRICULUM_TYPES = set(v5.CURRICULUM_TYPES)
SPECIALIZED_TEACHING_TYPES = {"Algorithm", "OperationRule", "ComplexityMetric"}
TEACHING_TYPES = CURRICULUM_TYPES | SPECIALIZED_TEACHING_TYPES

DISPLAY_NAMES = {
    **v5.DISPLAY_NAMES,
    "has_algorithm": "包含算法",
    "has_operation_rule": "包含操作规则",
    "has_complexity_metric": "具有复杂度指标",
}

RELATION_SCHEMA: dict[str, tuple[set[str], set[str]]] = {
    **v5.RELATION_SCHEMA,
    "part_of": (TEACHING_TYPES, TEACHING_TYPES),
    "prerequisite_of": (TEACHING_TYPES - {"KnowledgeDomain"}, TEACHING_TYPES - {"KnowledgeDomain"}),
    "supported_in_language": (TEACHING_TYPES, {"ProgrammingLanguage"}),
    "has_syntax_element": (TEACHING_TYPES, {"SyntaxElement"}),
    "has_code_structure": ({"KnowledgePoint", "Algorithm", "OperationRule"}, {"CodeStructure"}),
    "has_code_example": (TEACHING_TYPES, {"CodeExample"}),
    "assesses": ({"Question"}, TEACHING_TYPES | {"Ability"}),
    "requires_ability": (TEACHING_TYPES | {"Question"}, {"Ability"}),
    "develops_ability": (TEACHING_TYPES, {"Ability"}),
    "supports_practice": ({"LibraryFramework"}, TEACHING_TYPES),
    "may_cause": (TEACHING_TYPES | {"SyntaxElement", "CodeStructure", "Ability"}, {"ErrorPattern"}),
    "confused_with": (TEACHING_TYPES | {"SyntaxElement"}, TEACHING_TYPES | {"SyntaxElement"}),
    "equivalent_to": (
        TEACHING_TYPES | {"SyntaxElement", "ProgrammingLanguage", "CodeStructure", "Ability", "ErrorPattern"},
        TEACHING_TYPES | {"SyntaxElement", "ProgrammingLanguage", "CodeStructure", "Ability", "ErrorPattern"},
    ),
    "differs_from": (TEACHING_TYPES | {"SyntaxElement", "ProgrammingLanguage"}, TEACHING_TYPES | {"SyntaxElement", "ProgrammingLanguage"}),
    "has_algorithm": (CURRICULUM_TYPES | {"Algorithm"}, {"Algorithm"}),
    "has_operation_rule": (TEACHING_TYPES, {"OperationRule"}),
    "has_complexity_metric": (TEACHING_TYPES, {"ComplexityMetric"}),
}


def validate_graph_schema(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    semantic_types: set[str],
) -> dict[str, Any]:
    """Validate endpoint types against v6 without mutating graph contents."""
    violations: list[dict[str, Any]] = []
    generic_semantic_schema = (
        {"KnowledgeDomain", "KnowledgeUnit", "KnowledgePoint", "Algorithm"},
        {"KnowledgeUnit", "KnowledgePoint", "Algorithm", "OperationRule", "ComplexityMetric"},
    )
    for edge in edges:
        relation = str(edge.get("type", ""))
        source = nodes.get(str(edge.get("source", "")))
        target = nodes.get(str(edge.get("target", "")))
        if not source or not target:
            violations.append({"edge_id": edge.get("id", ""), "reason": "relation endpoint is missing"})
            continue
        schema = RELATION_SCHEMA.get(relation)
        if schema is None and relation in semantic_types:
            schema = generic_semantic_schema
        if schema is None:
            violations.append({"edge_id": edge.get("id", ""), "relation": relation, "reason": "undefined relation type"})
            continue
        source_type = str(source.get("type", ""))
        target_type = str(target.get("type", ""))
        if source_type not in schema[0] or target_type not in schema[1]:
            violations.append(
                {
                    "edge_id": edge.get("id", ""),
                    "relation": relation,
                    "source_type": source_type,
                    "target_type": target_type,
                    "reason": "endpoint types violate schema v6",
                }
            )
    return {
        "valid": not violations,
        "violation_count": len(violations),
        "violation_type_distribution": dict(Counter(item.get("relation", "unknown") for item in violations)),
        "violations": violations[:100],
    }


def relation_is_factually_valid(edge: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    """v5 language and syntax factual constraints remain valid in v6."""
    return v5.relation_is_factually_valid(edge, nodes)
