"""编程领域标准知识目录的读取、匹配与层级校验工具。"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any


DEFAULT_CATALOG = "work/oop_kg_demo/data/programming_curriculum_v0_2.json"


class CurriculumCatalog:
    """标准目录是正式教学层级的唯一来源，不由模型自由生成。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        nodes = payload.get("nodes", [])
        if not isinstance(nodes, list):
            raise ValueError("标准知识目录的 nodes 必须是数组。")
        self.payload = payload
        self.nodes = [item for item in nodes if isinstance(item, dict)]
        self.by_id = {str(item.get("id", "")): item for item in self.nodes}
        if len(self.by_id) != len(self.nodes) or "ROOT" not in self.by_id:
            raise ValueError("标准知识目录缺少唯一节点 ID，或缺少 ROOT 节点。")
        self._validate_tree()
        self.alias_index = self._build_alias_index()

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CATALOG) -> "CurriculumCatalog":
        catalog_path = Path(path)
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("标准知识目录顶层必须是对象。")
        return cls(payload)

    def node(self, node_id: str) -> dict[str, Any]:
        return self.by_id[node_id]

    def ancestor_ids(self, node_id: str) -> list[str]:
        result: list[str] = []
        current = node_id
        while current:
            result.append(current)
            current = str(self.by_id[current].get("parent_id", ""))
        return result

    def match_name(self, value: str) -> dict[str, Any] | None:
        normalized = normalize_text(value)
        if not normalized:
            return None
        node_id = self.alias_index.get(normalized)
        return self.by_id.get(node_id) if node_id else None

    def match_text(self, text: str, limit: int = 12) -> list[dict[str, Any]]:
        normalized_text = normalize_text(text)
        matches: list[tuple[int, dict[str, Any], str]] = []
        seen: set[str] = set()
        for alias, node_id in self.alias_index.items():
            if len(alias) < 2 or alias not in normalized_text or node_id in seen:
                continue
            seen.add(node_id)
            node = self.by_id[node_id]
            matches.append((len(alias), node, alias))
        matches.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
        return [item[1] for item in matches[:limit]]

    def domain_candidates(self, text: str) -> list[str]:
        result: list[str] = []
        for node in self.match_text(text, limit=30):
            path = list(reversed(self.ancestor_ids(str(node["id"]))))
            if len(path) >= 2:
                domain_name = str(self.by_id[path[1]].get("name", ""))
                if domain_name and domain_name not in result:
                    result.append(domain_name)
        return result

    def _build_alias_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for node in self.nodes:
            node_id = str(node["id"])
            values = [str(node.get("name", ""))]
            values.extend(str(item) for item in node.get("aliases", []) if str(item).strip())
            values.extend(str(item) for item in node.get("keywords", []) if str(item).strip())
            for value in values:
                key = normalize_text(value)
                if key and (key not in index or node_id < index[key]):
                    index[key] = node_id
        return index

    def _validate_tree(self) -> None:
        for node_id, node in self.by_id.items():
            parent_id = str(node.get("parent_id", ""))
            if node_id == "ROOT":
                if parent_id:
                    raise ValueError("ROOT 节点不能有父节点。")
                continue
            if parent_id not in self.by_id:
                raise ValueError(f"节点 {node_id} 的父节点不存在：{parent_id}")
            visited: set[str] = set()
            current = node_id
            while current:
                if current in visited:
                    raise ValueError(f"标准知识目录存在层级环：{node_id}")
                visited.add(current)
                current = str(self.by_id[current].get("parent_id", ""))


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = re.sub(r"[\s_\-·.。,:：;；()（）\[\]【】{}<>《》/\\]+", "", text)
    return text

