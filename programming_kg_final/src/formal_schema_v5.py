"""正式编程知识图谱 v5 的类型迁移、质量闸门与前端兼容导出。"""

from __future__ import annotations

import copy
import hashlib
import re
from collections import Counter, defaultdict
from typing import Any


CURRICULUM_TYPES = {"KnowledgeDomain", "KnowledgeUnit", "KnowledgePoint"}

DISPLAY_NAMES = {
    "part_of": "属于",
    "prerequisite_of": "前置依赖",
    "supported_in_language": "语言支持",
    "belongs_to_language": "属于语言",
    "written_in": "使用语言",
    "has_syntax_element": "具有语法元素",
    "has_code_structure": "具有代码结构",
    "has_code_example": "具有示例代码",
    "syntax_used_in_example": "用于示例",
    "appears_in_example": "出现于示例",
    "assesses": "考察",
    "requires_ability": "需要能力",
    "develops_ability": "培养能力",
    "supports_language": "支持语言",
    "built_on_platform": "构建于平台",
    "supports_practice": "支持实践",
    "may_cause": "可能导致",
    "confused_with": "易混淆",
    "equivalent_to": "等价于",
    "differs_from": "不同于",
    "inherits_from": "继承自",
    "implements_interface": "实现接口",
}

RELATION_SCHEMA: dict[str, tuple[set[str], set[str]]] = {
    "part_of": (CURRICULUM_TYPES, CURRICULUM_TYPES),
    "prerequisite_of": ({"KnowledgeUnit", "KnowledgePoint"}, {"KnowledgeUnit", "KnowledgePoint"}),
    "supported_in_language": (CURRICULUM_TYPES, {"ProgrammingLanguage"}),
    "belongs_to_language": ({"SyntaxElement"}, {"ProgrammingLanguage"}),
    "written_in": ({"CodeStructure", "CodeExample"}, {"ProgrammingLanguage"}),
    # 课程领域、单元和知识点都可以直接关联教学语法或代码示例。
    "has_syntax_element": (CURRICULUM_TYPES, {"SyntaxElement"}),
    "has_code_structure": ({"KnowledgePoint"}, {"CodeStructure"}),
    "has_code_example": (CURRICULUM_TYPES, {"CodeExample"}),
    "syntax_used_in_example": ({"SyntaxElement"}, {"CodeExample"}),
    "appears_in_example": ({"CodeStructure"}, {"CodeExample"}),
    "assesses": ({"Question"}, CURRICULUM_TYPES | {"Ability"}),
    "requires_ability": ({"KnowledgePoint", "Question"}, {"Ability"}),
    # “需要能力”描述解题或学习的前置要求；“培养能力”描述知识点完成学习后形成的能力。
    "develops_ability": (CURRICULUM_TYPES, {"Ability"}),
    "supports_language": ({"TechnologyPlatform", "LibraryFramework"}, {"ProgrammingLanguage"}),
    "built_on_platform": ({"LibraryFramework"}, {"TechnologyPlatform"}),
    "supports_practice": ({"LibraryFramework"}, CURRICULUM_TYPES),
    "may_cause": ({"KnowledgeUnit", "KnowledgePoint", "SyntaxElement", "CodeStructure", "Ability"}, {"ErrorPattern"}),
    "confused_with": ({"KnowledgePoint", "SyntaxElement"}, {"KnowledgePoint", "SyntaxElement"}),
    "equivalent_to": (
        CURRICULUM_TYPES | {"SyntaxElement", "ProgrammingLanguage", "CodeStructure", "Ability", "ErrorPattern"},
        CURRICULUM_TYPES | {"SyntaxElement", "ProgrammingLanguage", "CodeStructure", "Ability", "ErrorPattern"},
    ),
    "differs_from": (
        {"KnowledgePoint", "SyntaxElement", "ProgrammingLanguage"},
        {"KnowledgePoint", "SyntaxElement", "ProgrammingLanguage"},
    ),
    "inherits_from": ({"CodeStructure"}, {"CodeStructure"}),
    "implements_interface": ({"CodeStructure"}, {"CodeStructure"}),
}

VALID_SYNTAX_BY_LANGUAGE = {
    "Java": {
        "abstract", "break", "case", "catch", "continue", "else", "extends", "final", "for", "if",
        "implements", "import", "new", "private", "protected", "public", "return", "static", "switch",
        "super", "this", "throw", "try", "while",
    },
    "Python": {"break", "continue", "def", "else", "for", "if", "import", "return", "try", "while"},
    "C++": {
        "break", "case", "catch", "const", "continue", "else", "for", "if", "new", "private",
        "protected", "public", "return", "static", "switch", "template", "this", "try", "while",
        "double", "float", "long double", "unsigned char", "unsigned int", "virtual", "throw",
        "using 声明", "private 继承",
    },
}

DENIED_CONCEPT_LANGUAGE_PAIRS = {
    ("指针", "Java"),
    ("指针", "Python"),
    ("引用", "Python"),
    ("命名空间", "Java"),
    ("函数重载", "Python"),
    ("方法重载", "Python"),
}

LEGACY_NODE_TYPES = {"SyntaxElement": "SyntaxRule"}
LEGACY_RELATION_TYPES = {
    "supported_in_language": "implemented_in",
    "belongs_to_language": "implemented_in",
    "written_in": "implemented_in",
    "has_syntax_element": "has_syntax",
    "syntax_used_in_example": "used_in_example",
    "requires_ability": "requires_skill",
}


def stable_id(prefix: str, *parts: str) -> str:
    raw = ":".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def migrate_node(node: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(node)
    if migrated.get("type") == "SyntaxRule":
        migrated["legacy_type"] = "SyntaxRule"
        migrated["type"] = "SyntaxElement"
    return migrated


def migrate_relation_type(edge: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> str | None:
    relation = str(edge.get("type", ""))
    source = nodes.get(str(edge.get("source", "")), {})
    if relation == "expresses_concept":
        # 与 has_syntax_element 互为反向事实，正式图谱只存规范方向。
        return None
    if relation == "implemented_in":
        source_type = str(source.get("type", ""))
        if source_type == "SyntaxElement":
            return "belongs_to_language"
        if source_type in CURRICULUM_TYPES:
            return "supported_in_language"
        if source_type in {"CodeStructure", "CodeExample"}:
            return "written_in"
        return None
    return {
        "has_syntax": "has_syntax_element",
        "used_in_example": "syntax_used_in_example",
        "requires_skill": "requires_ability",
    }.get(relation, relation)


def relation_is_factually_valid(edge: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    relation = str(edge.get("type", ""))
    source = nodes[str(edge["source"])]
    target = nodes[str(edge["target"])]
    if relation == "belongs_to_language":
        valid_terms = VALID_SYNTAX_BY_LANGUAGE.get(str(target.get("name", "")), set())
        if str(source.get("name", "")).lower() not in valid_terms:
            return False, "语法元素不属于目标编程语言"
    if relation == "supported_in_language":
        pair = (str(source.get("name", "")), str(target.get("name", "")))
        if pair in DENIED_CONCEPT_LANGUAGE_PAIRS:
            return False, "概念与语言的支持关系会造成错误或强烈误导"
    return True, ""


def code_example_quality(node: dict[str, Any]) -> tuple[bool, str, int]:
    sources = [source for source in node.get("sources", []) if isinstance(source, dict)]
    roles = {str(source.get("material_role", "")) for source in sources}
    if not sources:
        return False, "缺少来源证据", 0
    if roles != {"code_example"}:
        return False, f"来源角色不是纯代码示例：{sorted(roles)}", 0
    content = "\n".join(str(source.get("content", "")) for source in sources)
    strong_patterns = [
        r"#include\s*[<\"]", r"\bclass\s+[A-Za-z_]\w*", r"\binterface\s+[A-Za-z_]\w*",
        r"\bdef\s+[A-Za-z_]\w*\s*\(", r"\b(public|private|protected)\s*:", r"System\.out\.",
        r"\bstd::(cout|cin|vector|string)", r"\b(print|input)\s*\(", r"\b(for|while|if|switch)\s*\(",
        r"\b(try|except|catch|finally)\b", r"\breturn\s+[^。；]+", r"\b(import|from)\s+[A-Za-z_]",
        r"\b(template|typename)\s*<", r"\bnew\s+[A-Za-z_]\w*\s*\(", r"\b[A-Za-z_]\w*\s*\([^)]*\)\s*\{",
    ]
    score = sum(1 for pattern in strong_patterns if re.search(pattern, content, flags=re.I))
    declaration = bool(re.search(r"\b(?:int|double|float|char|bool|boolean|String|str|list|dict)\s+[A-Za-z_]\w*\s*(?:[=;,)])", content))
    punctuation = int("{" in content and "}" in content) + int(";" in content) + int("=" in content)
    score += int(declaration) + punctuation
    narrative_markers = sum(content.count(term) for term in ("定义：", "包括：", "用于", "表示", "注意：", "步骤", "方法说明"))
    if score < 2:
        return False, "缺少足够代码结构，疑似概念说明或 API 列表", score
    if len(content) > 180 and narrative_markers >= 2 and score < 4:
        return False, "说明性文字占主导，代码片段应重新切分", score
    return True, "", score


def infer_structure_kind(node: dict[str, Any], relation_roles: set[str]) -> str:
    text = " ".join(
        [str(node.get("description", "")), str(node.get("name", "")), *[str(x) for x in relation_roles]]
    ).lower()
    if "interface_target" in relation_roles or "接口" in text:
        return "interface"
    if relation_roles & {"inherits_source", "inherits_target", "implements_source"} or "类结构" in text or "class" in text:
        return "class"
    if "方法结构" in text or "method" in text:
        return "method"
    if "函数" in text or "function" in text:
        return "function"
    return "symbol"


def scope_code_structures(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    code_ids = {node_id for node_id, node in nodes.items() if node.get("type") == "CodeStructure"}
    if not code_ids:
        return nodes, edges, []
    appearances: dict[str, set[str]] = defaultdict(set)
    relation_roles: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        relation = str(edge.get("type", ""))
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if relation == "appears_in_example" and source in code_ids and target in nodes:
            appearances[source].add(target)
        elif relation == "inherits_from":
            relation_roles[source].add("inherits_source")
            relation_roles[target].add("inherits_target")
        elif relation == "implements_interface":
            relation_roles[source].add("implements_source")
            relation_roles[target].add("interface_target")

    clone_by_pair: dict[tuple[str, str], str] = {}
    new_nodes = {node_id: node for node_id, node in nodes.items() if node_id not in code_ids}
    for original_id, example_ids in appearances.items():
        original = nodes[original_id]
        for example_id in sorted(example_ids):
            clone_id = stable_id("CodeStructure", original_id, example_id)
            clone_by_pair[(original_id, example_id)] = clone_id
            example = nodes[example_id]
            source_chunks = sorted(set(example.get("source_chunk_ids", [])) & set(original.get("source_chunk_ids", [])))
            clone = dict(original)
            clone.update(
                {
                    "id": clone_id,
                    "structure_kind": infer_structure_kind(original, relation_roles.get(original_id, set())),
                    "scope_example_id": example_id,
                    "original_code_structure_id": original_id,
                    "source_chunk_ids": source_chunks or list(example.get("source_chunk_ids", [])),
                    "sources": list(example.get("sources", [])),
                }
            )
            new_nodes[clone_id] = clone

    rejected: list[dict[str, Any]] = []
    new_edges: list[dict[str, Any]] = []
    for edge in edges:
        relation = str(edge.get("type", ""))
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if relation == "appears_in_example" and source in code_ids:
            clone_id = clone_by_pair.get((source, target))
            if clone_id:
                copied = dict(edge)
                copied["source"] = clone_id
                copied["id"] = stable_id("edge", clone_id, relation, target)
                new_edges.append(copied)
            continue
        if relation in {"inherits_from", "implements_interface"} and source in code_ids and target in code_ids:
            common_examples = appearances.get(source, set()) & appearances.get(target, set())
            for example_id in sorted(common_examples):
                scoped_source = clone_by_pair[(source, example_id)]
                scoped_target = clone_by_pair[(target, example_id)]
                copied = dict(edge)
                copied.update(
                    {
                        "id": stable_id("edge", scoped_source, relation, scoped_target),
                        "source": scoped_source,
                        "target": scoped_target,
                    }
                )
                new_edges.append(copied)
            if not common_examples:
                rejected.append({"edge": edge, "reason": "继承/接口关系两端没有共同代码示例作用域"})
            continue
        if source in code_ids or target in code_ids:
            rejected.append({"edge": edge, "reason": "代码结构关系无法安全迁移到局部作用域"})
            continue
        new_edges.append(edge)
    return new_nodes, new_edges, rejected


def validate_graph_schema(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    semantic_types: set[str],
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    for edge in edges:
        relation = str(edge.get("type", ""))
        source = nodes.get(str(edge.get("source", "")))
        target = nodes.get(str(edge.get("target", "")))
        if not source or not target:
            violations.append({"edge_id": edge.get("id", ""), "reason": "关系端点不存在"})
            continue
        schema = RELATION_SCHEMA.get(relation)
        if schema is None and relation in semantic_types:
            schema = ({"KnowledgeDomain", "KnowledgeUnit"}, {"KnowledgeUnit", "KnowledgePoint"})
        if schema is None:
            violations.append({"edge_id": edge.get("id", ""), "reason": f"未定义关系类型：{relation}"})
            continue
        if source.get("type") not in schema[0] or target.get("type") not in schema[1]:
            violations.append(
                {
                    "edge_id": edge.get("id", ""),
                    "relation": relation,
                    "source_type": source.get("type"),
                    "target_type": target.get("type"),
                    "reason": "头尾实体类型不符合正式 Schema",
                }
            )
    return {
        "valid": not violations,
        "violation_count": len(violations),
        "violation_type_distribution": dict(Counter(item.get("relation", "unknown") for item in violations)),
        "violations": violations[:100],
    }


def relation_types_compatible(
    relation: str,
    source_type: str,
    target_type: str,
    semantic_types: set[str],
) -> bool:
    schema = RELATION_SCHEMA.get(relation)
    if schema is None and relation in semantic_types:
        schema = ({"KnowledgeDomain", "KnowledgeUnit"}, {"KnowledgeUnit", "KnowledgePoint"})
    return bool(schema and source_type in schema[0] and target_type in schema[1])


def build_frontend_compatible_graph(graph: dict[str, Any]) -> dict[str, Any]:
    compatible = copy.deepcopy(graph)
    compatible["schema_version"] = "programming_kg_frontend_compatible_v4_from_v5"
    for node in compatible.get("nodes", []):
        canonical_type = str(node.get("type", ""))
        node["canonical_type"] = canonical_type
        node["type"] = LEGACY_NODE_TYPES.get(canonical_type, canonical_type)
    for edge in compatible.get("edges", []):
        canonical_type = str(edge.get("type", ""))
        legacy_type = LEGACY_RELATION_TYPES.get(canonical_type, canonical_type)
        edge["canonical_type"] = canonical_type
        edge["type"] = legacy_type
        edge["relation_name"] = {
            "implemented_in": "实现于",
            "has_syntax": "具有语法",
            "used_in_example": "用于示例",
            "requires_skill": "需要能力",
        }.get(legacy_type, edge.get("relation_name", legacy_type))
        edge["neo4j_type"] = edge["relation_name"]
    compatible.setdefault("metadata", {})["compatibility_note"] = (
        "该文件供旧前端过渡使用；canonical_type 保存 v5 正式类型。"
    )
    compatible["schema"]["node_types"] = sorted({node["type"] for node in compatible.get("nodes", [])})
    compatible["schema"]["edge_types"] = sorted({edge["type"] for edge in compatible.get("edges", [])})
    return compatible
