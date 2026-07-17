"""
第五阶段 B：习题到知识点自动映射。

输入：
    output/question_mapping/questions.json
    output/graph_normalized/standard_graph.json

输出：
    output/question_mapping/question_knowledge_links.json
    output/question_mapping/question_mapping_report.json

脚本先用规则从题干和代码中召回候选知识点，再可选调用通义千问或 DeepSeek
做语义精判。Demo 阶段推荐默认使用 qwen；离线调试可以加 --no-llm。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_QUESTIONS = "work/oop_kg_demo/output/programming_kg/questions/official_questions.json"
DEFAULT_GRAPH = "work/oop_kg_demo/output/programming_kg/graph_hierarchy/standard_graph.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/programming_kg/question_mapping"

GOLD_NAME_NORMALIZATION = {
    "属性": "属性与方法",
    "方法": "属性与方法",
    "信息隐藏": "封装",
    "重写": "方法重写",
    "父类": "父类与子类",
    "类型": "类型系统",
}
ASSESSABLE_TYPES = {"KnowledgeDomain", "KnowledgeUnit", "KnowledgePoint", "SyntaxElement", "SyntaxRule"}
NEGATIVE_QUESTION_CUES = ("不正确", "错误的是", "不包括", "不能", "不符合", "不属于")

# 映射元数据是正式版的扩展契约。默认不回写历史题库；只有显式传入 --add-metadata
# 才会在新生成的映射中写入，避免把当前已人工确认的 20 道题悄悄改成另一套数据。
QUESTION_MAPPING_METADATA_POLICY = {
    "role_weights": {"primary": 1.0, "secondary": 0.6},
    "cognitive_levels": ["remember", "understand", "apply", "analyze", "evaluate", "create"],
    "mapping_statuses": ["draft", "reviewed", "approved"],
}

PROVIDER_CONFIGS = {
    "qwen": {
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus-2025-07-28",
    },
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
    },
}

# 这些规则把编程题中的代码特征和中文表述映射到现有图谱知识点。
# 它不是最终答案，只负责“召回候选”，最后还可以由 LLM 精判。
KEYWORD_TO_KNOWLEDGE = {
    "for": ["for循环"],
    "while": ["while循环"],
    "break": ["循环控制"],
    "continue": ["循环控制"],
    "if": ["if语句"],
    "switch": ["switch语句"],
    "函数": ["函数定义与调用"],
    "函数体": ["函数定义与调用"],
    "方法体": ["函数定义与调用"],
    "定义方法": ["函数定义与调用"],
    "重载": ["函数重载", "方法重载", "操作符重载"],
    "缺省参数": ["缺省参数"],
    "默认参数": ["缺省参数"],
    "defaultparam": ["缺省参数"],
    "defaulparam": ["缺省参数"],
    "内联函数": ["内联函数"],
    "inline": ["内联函数"],
    "参数": ["参数与返回值"],
    "return": ["参数与返回值"],
    "作用域": ["作用域与生命周期"],
    "指针": ["指针"],
    "引用": ["引用"],
    "队列": ["队列"],
    "queue": ["队列"],
    "栈": ["栈"],
    "stack": ["栈"],
    "链表": ["链表"],
    "template": ["泛型与模板"],
    "模板": ["泛型与模板"],
    "virtual": ["动态绑定"],
    "异常": ["异常处理与调试"],
    "try": ["异常捕获与处理"],
    "catch": ["异常捕获与处理"],
    "文件": ["文件与目录操作"],
    "线程": ["进程与线程"],
    "thread": ["进程与线程"],
    "class": ["类"],
    "类": ["类"],
    "object": ["对象"],
    "对象": ["对象"],
    "new ": ["对象的动态创建与销毁"],
    "delete": ["对象的动态创建与销毁"],
    "属性": ["属性"],
    "变量": ["属性"],
    "field": ["属性"],
    "方法": ["方法"],
    "method": ["方法"],
    "void ": ["方法"],
    "封装": ["封装", "信息隐藏"],
    "信息隐藏": ["信息隐藏", "封装"],
    "private": ["访问控制", "封装"],
    "protected": ["访问控制"],
    "public": ["访问控制", "封装"],
    "extends": ["继承", "父类"],
    "继承": ["继承"],
    "父类": ["父类", "继承"],
    "子类": ["继承", "父类"],
    "override": ["重写"],
    "@override": ["重写"],
    "重写": ["重写"],
    "覆盖": ["重写"],
    "多态": ["多态"],
    "父类引用": ["向上转型", "多态"],
    "父类 引用": ["向上转型", "多态"],
    "new dog": ["向上转型"],
    "new child": ["向上转型"],
    "向上转型": ["向上转型"],
    "动态绑定": ["动态绑定", "多态"],
    "动态多态性": ["动态绑定"],
    "虚函数": ["动态绑定"],
    "运行期": ["动态绑定"],
    "运行时": ["动态绑定"],
    "实际对象类型": ["动态绑定", "向上转型", "类型"],
    "编译期类型": ["类型", "向上转型"],
    "类型": ["类型"],
    "interface": ["接口"],
    "implements": ["接口"],
    "接口": ["接口"],
    "多重继承": ["多重继承", "接口"],
    "abstract": ["abstract", "抽象类", "抽象"],
    "抽象类": ["抽象类", "abstract", "抽象"],
    "抽象": ["抽象"],
    "final": ["final"],
    "面向对象": ["面向对象编程"],
    "oop": ["面向对象编程"],
    "常数据成员": ["常成员"],
    "常量数据成员": ["常成员"],
    "常成员函数": ["常成员"],
    "常量成员函数": ["常成员"],
    "静态数据成员": ["静态成员"],
    "拷贝构造": ["拷贝构造函数"],
    "复制构造": ["拷贝构造函数"],
    "友元": ["友元"],
    "操作符重载": ["操作符重载"],
    "运算符重载": ["操作符重载"],
    "虚基类": ["虚继承"],
    "访问控制": ["访问控制"],
    "公用继承": ["访问控制", "父类与子类"],
    "私有继承": ["访问控制", "父类与子类"],
    "保护继承": ["访问控制", "父类与子类"],
    "公用成员": ["访问控制"],
    "私有成员": ["访问控制"],
    "保护成员": ["访问控制"],
    "消息": ["消息传递"],
    "消息传递": ["消息传递"],
}


@dataclass
class MappingFiles:
    links: Path
    report: Path
    cache_dir: Path
    mapped_questions: Path
    review: Path


class LLMClient:
    """简单的 OpenAI-compatible Chat Completions 客户端。"""

    def __init__(
        self,
        provider: str,
        model: str | None,
        base_url: str | None,
        timeout: int,
        retries: int,
        cache_dir: Path,
        use_cache: bool,
    ) -> None:
        config = PROVIDER_CONFIGS[provider]
        self.provider = provider
        self.model = model or config["model"]
        self.base_url = base_url or config["base_url"]
        self.timeout = timeout
        self.retries = retries
        self.cache_dir = cache_dir
        self.use_cache = use_cache
        self.api_key = os.getenv(config["api_key_env"], "").strip()
        if not self.api_key:
            raise RuntimeError(f"未找到环境变量 {config['api_key_env']}，无法调用 {provider} API。")

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        cache_key = hashlib.sha256(
            json.dumps(
                {"provider": self.provider, "model": self.model, "messages": messages},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if self.use_cache and cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                request = urllib.request.Request(self.base_url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                content = response_payload["choices"][0]["message"]["content"]
                parsed = parse_json_object(content)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
                return parsed
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace").strip()
                last_error = RuntimeError(f"HTTP {exc.code}: {detail[:1200]}")
                if attempt < self.retries:
                    time.sleep(1.2 * attempt)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.2 * attempt)
        raise RuntimeError(f"{self.provider} API 调用失败：{last_error}")


class QuestionMapper:
    """把一道习题映射到标准图谱中的知识节点。"""

    def __init__(
        self,
        graph: dict[str, Any],
        llm_client: LLMClient | None,
        max_links: int,
        llm_ambiguous_only: bool,
        course_id: str | None = None,
        use_verified_answer_context: bool = False,
    ) -> None:
        self.graph = graph
        self.llm_client = llm_client
        self.max_links = max_links
        self.llm_ambiguous_only = llm_ambiguous_only
        self.course_id = course_id
        self.use_verified_answer_context = use_verified_answer_context
        # 课程中心化图谱中，同名知识点会在不同课程拥有各自的本地节点。
        # 因此题目映射必须限定到所属课程，不能跨课程从全图召回候选。
        self.all_assessable_nodes = self._load_knowledge_nodes(graph, course_id=course_id)
        self.knowledge_nodes = [
            node
            for node in self.all_assessable_nodes
            if node["type"] in {"KnowledgePoint", "SyntaxElement", "SyntaxRule"}
        ]
        self.name_to_node = {node["name"]: node for node in self.knowledge_nodes}
        self.gold_name_to_node = self._build_gold_name_index(self.all_assessable_nodes)

    def map_question(self, question: dict[str, Any]) -> dict[str, Any]:
        candidates = self.recall_candidates(question)
        answer_context = self.verified_answer_context(question) if self.use_verified_answer_context else ""
        gold_items = question.get("gold_knowledge_points", [])
        if isinstance(gold_items, list) and gold_items:
            links, unresolved = self.gold_links(gold_items)
            return {
                "question_id": question["question_id"],
                "method": "human_gold",
                "llm_error": "",
                "candidate_count": len(candidates),
                "candidates": candidates,
                "links": links,
                "unresolved_gold_items": unresolved,
                "language_context": question.get("language", ""),
            }
        if self.llm_client is None:
            links = self.rule_links(question, candidates)
            method = "rule"
            llm_error = ""
        elif self.llm_ambiguous_only and not self._requires_llm(candidates):
            links = self.rule_links(question, candidates)
            method = "rule_deterministic"
            llm_error = ""
        else:
            try:
                links = self.llm_links(question, candidates, answer_context)
                method = self.llm_client.provider
                llm_error = ""
            except Exception as exc:
                # API 出问题时不让整条流程断掉，自动退回规则结果，报告里会记录原因。
                links = self.rule_links(question, candidates)
                method = "rule_fallback"
                llm_error = str(exc)

        return {
            "question_id": question["question_id"],
            "method": method,
            "llm_error": llm_error,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "links": links,
            "unresolved_gold_items": [],
            "language_context": question.get("language", ""),
            "verified_answer_context_used": bool(answer_context),
        }

    def gold_links(
        self,
        gold_items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """人工金标准优先，语言名只保留为题目上下文，不生成考察边。"""
        links: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in gold_items:
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get("name", "")).strip()
            if raw_name.casefold() in {"java", "python", "c++", "cpp"}:
                continue
            canonical_name = GOLD_NAME_NORMALIZATION.get(raw_name, raw_name)
            node = self.gold_name_to_node.get(canonical_name.casefold())
            if not node:
                unresolved.append({"name": raw_name, "normalized_name": canonical_name, "role": item.get("role")})
                continue
            if node["id"] in seen:
                if str(item.get("role", "secondary")) == "primary":
                    for link in links:
                        if link["knowledge_node_id"] == node["id"]:
                            link["role"] = "primary"
                continue
            seen.add(node["id"])
            links.append(
                {
                    "knowledge_node_id": node["id"],
                    "knowledge_name": node["name"],
                    "knowledge_type": node["type"],
                    "role": "primary" if str(item.get("role")) == "primary" else "secondary",
                    "confidence": 1.0,
                    "evidence": f"人工金标准：{raw_name}",
                    "rank": len(links) + 1,
                }
            )
        links.sort(key=lambda link: (0 if link["role"] == "primary" else 1, link["rank"]))
        for index, link in enumerate(links, start=1):
            link["rank"] = index
        return links[: self.max_links], unresolved

    @staticmethod
    def _build_gold_name_index(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for node in nodes:
            for term in [node["name"], *node.get("aliases", [])]:
                key = str(term).strip().casefold()
                if key and key not in index:
                    index[key] = node
        return index

    @staticmethod
    def _requires_llm(candidates: list[dict[str, Any]]) -> bool:
        """只让模型裁决候选分数接近的习题，避免模型覆盖明显的规则证据。"""
        if not candidates:
            return False
        if len(candidates) == 1:
            return float(candidates[0].get("score", 0.0)) < 4.0
        top_score = float(candidates[0].get("score", 0.0))
        second_score = float(candidates[1].get("score", 0.0))
        # 第一候选命中强且领先至少 2 分时，主考知识点足够明确。
        return not (top_score >= 5.0 and top_score - second_score >= 2.0)

    def recall_candidates(self, question: dict[str, Any]) -> list[dict[str, Any]]:
        # 默认只看题干和代码。显式启用后，仅加入通过来源审核的正确选项，
        # 其余选项仍视为干扰项，不参与召回。
        stem_text = str(question.get("stem", "")).lower()
        code_text = str(question.get("code", "")).lower()
        options_text = "\n".join(str(option) for option in question.get("options", [])).lower()
        answer_context = self.verified_answer_context(question).lower() if self.use_verified_answer_context else ""
        # 否定题的正确选项通常是一个错误命题或例外项，只用于帮助模型理解题目，
        # 不参与候选召回，否则容易把干扰概念误当成主考点。
        answer_recall_context = "" if is_negative_question(stem_text) else answer_context
        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = {}

        for node in self.knowledge_nodes:
            name = node["name"]
            aliases = [name] + list(node.get("aliases", []))
            for alias in aliases:
                alias_text = str(alias).strip().lower()
                if not alias_text:
                    continue
                if alias_text in stem_text and not only_occurs_inside_broad_compounds(stem_text, alias_text):
                    add_score(scores, evidence, name, 4.0, f"题干命中知识点名称/别名：{alias}")
                elif alias_text in answer_recall_context and not only_occurs_inside_broad_compounds(
                    answer_recall_context, alias_text
                ):
                    add_score(scores, evidence, name, 3.5, f"来源验证的正确选项命中知识点名称/别名：{alias}")
                elif alias_text in options_text and not only_occurs_inside_broad_compounds(options_text, alias_text):
                    add_score(scores, evidence, name, 1.2, f"题目选项低权重命中知识点名称/别名：{alias}")
                elif alias_text in code_text:
                    add_score(scores, evidence, name, 1.0, f"代码中出现：{alias}")

        for keyword, names in KEYWORD_TO_KNOWLEDGE.items():
            keyword_lower = keyword.lower()
            if keyword_lower in stem_text and not only_occurs_inside_broad_compounds(stem_text, keyword_lower):
                for name in names:
                    if name in self.name_to_node:
                        add_score(scores, evidence, name, 3.0, f"题干命中编程特征：{keyword}")
            elif keyword_lower in answer_recall_context and not only_occurs_inside_broad_compounds(
                answer_recall_context, keyword_lower
            ):
                for name in names:
                    if name in self.name_to_node:
                        add_score(scores, evidence, name, 2.7, f"来源验证的正确选项命中编程特征：{keyword}")
            elif keyword_lower in options_text and not only_occurs_inside_broad_compounds(options_text, keyword_lower):
                for name in names:
                    if name in self.name_to_node:
                        add_score(scores, evidence, name, 0.8, f"题目选项低权重命中编程特征：{keyword}")
            elif keyword_lower in code_text:
                for name in names:
                    if name in self.name_to_node:
                        add_score(scores, evidence, name, 0.8, f"代码中出现编程特征：{keyword}")

        candidates = []
        for name, score in scores.items():
            node = self.name_to_node[name]
            candidates.append(
                {
                    "knowledge_node_id": node["id"],
                    "knowledge_name": name,
                    "knowledge_type": node["type"],
                    "description": node.get("description", ""),
                    "score": round(score, 3),
                    "evidence": evidence.get(name, [])[:5],
                }
            )
        candidates.sort(key=lambda item: (-item["score"], item["knowledge_name"]))
        return candidates[:12]

    @staticmethod
    def verified_answer_context(question: dict[str, Any]) -> str:
        """Return only the source-verified correct option, never distractor options."""
        if str(question.get("type", "")) != "multiple_choice":
            return ""
        pairing = question.get("answer_pairing") if isinstance(question.get("answer_pairing"), dict) else {}
        completeness = question.get("answer_completeness") if isinstance(question.get("answer_completeness"), dict) else {}
        if (
            pairing.get("status") != "verified"
            or completeness.get("status") != "complete"
            or not question.get("formal_import_eligible")
        ):
            return ""
        match = re.search(r"[A-D]", str(question.get("answer", "")).upper())
        if not match:
            return ""
        answer_letter = match.group(0)
        for option in question.get("options", []):
            option_text = str(option).strip()
            if re.match(rf"^{answer_letter}\s*[\.．、\)]", option_text, flags=re.I):
                return option_text
        return ""

    def rule_links(self, question: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        # 规则模式用于离线兜底，宁愿少连一点，也不要把低分邻居误当成确定关系。
        # 低分候选仍会保留在 candidates 里，供 LLM 模式进一步判断。
        strong_candidates = [candidate for candidate in candidates if candidate["score"] >= 4.0]

        for index, candidate in enumerate(strong_candidates[: self.max_links]):
            role = "primary" if index < 2 else "secondary"
            confidence = min(0.95, 0.5 + candidate["score"] / 10)
            links.append(
                {
                    "knowledge_node_id": candidate["knowledge_node_id"],
                    "knowledge_name": candidate["knowledge_name"],
                    "knowledge_type": candidate["knowledge_type"],
                    "role": role,
                    "confidence": round(confidence, 3),
                    "evidence": "；".join(candidate.get("evidence", [])[:2]) or "规则召回候选知识点",
                    "rank": index + 1,
                }
            )
        return links

    def llm_links(
        self, question: dict[str, Any], candidates: list[dict[str, Any]], answer_context: str = ""
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []
        messages = build_prompt(question, candidates, self.max_links, answer_context)
        parsed = self.llm_client.complete_json(messages) if self.llm_client else {}
        raw_links = parsed.get("links", [])
        if not isinstance(raw_links, list):
            return self.rule_links(question, candidates)

        candidate_by_name = {item["knowledge_name"]: item for item in candidates}
        links: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_links:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("knowledge_name", "")).strip()
            if name not in candidate_by_name or name in seen:
                continue
            seen.add(name)
            candidate = candidate_by_name[name]
            role = str(raw.get("role", "secondary")).strip()
            if role not in {"primary", "secondary"}:
                role = "secondary"
            confidence = safe_confidence(raw.get("confidence"))
            if confidence < 0.75:
                continue
            links.append(
                {
                    "knowledge_node_id": candidate["knowledge_node_id"],
                    "knowledge_name": name,
                    "knowledge_type": candidate["knowledge_type"],
                    "role": role,
                    "confidence": confidence,
                    "evidence": str(raw.get("evidence", "")).strip() or "LLM 根据题干、代码和候选知识点判断",
                    "rank": len(links) + 1,
                }
            )
            if len(links) >= min(self.max_links, 3):
                break

        primary_seen = False
        for link in links:
            if link["role"] != "primary":
                continue
            if primary_seen:
                link["role"] = "secondary"
            else:
                primary_seen = True

        # 模型明确返回空列表或全部候选置信度不足时，保留为待复核，
        # 不再用词面规则强行补一条看似成功但语义错误的映射。
        if not links:
            return []
        return links

    @staticmethod
    def _load_knowledge_nodes(graph: dict[str, Any], course_id: str | None = None) -> list[dict[str, Any]]:
        nodes = graph.get("nodes", [])
        if not isinstance(nodes, list):
            raise ValueError("standard_graph.json 的 nodes 必须是数组。")
        result = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if course_id and str(node.get("course_id", "")) != course_id:
                continue
            if node.get("type") in ASSESSABLE_TYPES:
                result.append(
                    {
                        "id": str(node.get("id", "")),
                        "name": str(node.get("name", "")),
                        "type": str(node.get("type", "")),
                        "aliases": node.get("aliases", []) if isinstance(node.get("aliases"), list) else [],
                        "description": str(node.get("description", "")),
                    }
                )
        return [node for node in result if node["id"] and node["name"]]


def build_prompt(
    question: dict[str, Any],
    candidates: list[dict[str, Any]],
    max_links: int,
    verified_answer_context: str = "",
) -> list[dict[str, str]]:
    system = (
        "你是编程教育知识图谱专家。请只从候选知识点中选择本题真正考察的知识点，"
        "区分 primary 和 secondary，并输出严格 JSON。不要新增候选列表之外的知识点。"
        "代码中顺带出现的关键字、编程语言名称和干扰项不算考点。"
        "若候选都不能准确表达考点，必须返回空 links，严禁为了完成映射选择宽泛或仅词面重叠的节点。"
    )
    user = {
        "question_id": question["question_id"],
        "type": question.get("type_label") or question.get("type"),
        "language": question.get("language"),
        "stem": question.get("stem"),
        "code": question.get("code"),
        "options": question.get("options", []),
        "verified_correct_option": verified_answer_context,
        "candidates": [
            {
                "knowledge_name": item["knowledge_name"],
                "knowledge_type": item["knowledge_type"],
                "description": item.get("description", ""),
                "rule_evidence": item.get("evidence", []),
            }
            for item in candidates
        ],
        "output_format": {
            "question_id": question["question_id"],
            "links": [
                {
                    "knowledge_name": "候选知识点名称",
                    "role": "primary 或 secondary",
                    "confidence": "0 到 1 的小数",
                    "evidence": "题干或代码中的判断依据",
                }
            ],
        },
        "constraints": [
            f"最多输出 {min(max_links, 3)} 个知识点",
            "至少输出 1 个 primary，除非题目完全无法判断",
            "primary 表示不掌握就无法解题的核心知识，secondary 表示确实参与推理的辅助知识",
            "若题目要求补全或实现一个方法/函数体，优先选择“函数定义与调用”；只有题目实际考察形参与实参、返回值传递或调用结果时，才将“参数与返回值”作为 primary",
            "不要因为某个语法词只在代码中出现就把它选为考点",
            "题目考查概念或规则时优先选择 KnowledgePoint；仅当题目直接询问关键字或具体语法形式时，SyntaxElement 或 SyntaxRule 才能作为 primary",
            "对于包含“不正确、错误、不包括、不能、不符合”等表述的否定题，正确选项是例外项，不得仅凭正确选项中的词语确定考点",
            "若候选节点只与题干存在局部子串重叠、但语义不一致，输出空 links",
            "题目选项仅用于判断整道题的主题；错误选项和陪衬选项中的概念不能单独成为考点",
            "原则上只输出一个 primary；确有两个相互独立且缺一不可的核心考点时才允许两个 primary",
            "当具体知识点已经完整表达考点时，不再附加“类、对象、函数定义与调用、int、const、public”等宽泛或语法层候选",
            "模板实例化题以“泛型与模板”为 primary、“实例化”为 secondary，不把实例化结果的类型名称当作主考点",
            "缺省参数函数调用合法性题以“缺省参数”为 primary，不使用宽泛的“函数定义与调用”替代",
            "delete 动态对象语义题以“对象的动态创建与销毁”为 primary；若同时考察析构调用，可将“构造方法与析构方法”作为 secondary",
            "public、private、protected 以及公用/私有/保护继承造成的可访问性问题，以“访问控制”为 primary，不把关键字节点作为主考点",
            "knowledge_name 必须来自 candidates",
            "verified_correct_option 仅在原题答案来源与完整性均已验证时提供；可用于理解考点，但不得引入 candidates 之外的知识点",
        ],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]


def is_negative_question(text: str) -> bool:
    return any(cue in text for cue in NEGATIVE_QUESTION_CUES)


def only_occurs_inside_broad_compounds(text: str, term: str) -> bool:
    """避免把“面向对象”拆成“对象”，或把“虚基类”拆成宽泛的“类”。"""
    compounds = {
        "对象": ("面向对象",),
        "类": ("虚基类", "派生类", "基类", "子类", "父类", "抽象类", "友元类", "类模板"),
    }.get(term, ())
    if not compounds or term not in text:
        return False
    remaining = text
    for compound in sorted(compounds, key=len, reverse=True):
        remaining = remaining.replace(compound, "")
    return term not in remaining


def expand_with_neighbors(
    scores: dict[str, float],
    graph: dict[str, Any],
    name_to_node: dict[str, dict[str, Any]],
) -> dict[str, str]:
    id_to_name = {node["id"]: node["name"] for node in name_to_node.values()}
    active_ids = {name_to_node[name]["id"] for name in scores if name in name_to_node}
    expanded: dict[str, str] = {}
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source in active_ids and target in id_to_name:
            expanded[id_to_name[target]] = f"图谱邻居扩展：{id_to_name.get(source, source)} -> {id_to_name[target]}"
        if target in active_ids and source in id_to_name:
            expanded[id_to_name[source]] = f"图谱邻居扩展：{id_to_name.get(target, target)} -> {id_to_name[source]}"
    return {name: reason for name, reason in expanded.items() if name not in scores}


def add_score(
    scores: dict[str, float],
    evidence: dict[str, list[str]],
    name: str,
    score: float,
    reason: str,
) -> None:
    scores[name] = scores.get(name, 0.0) + score
    evidence.setdefault(name, [])
    if reason not in evidence[name]:
        evidence[name].append(reason)


def build_question_text(question: dict[str, Any]) -> str:
    parts = [
        question.get("stem", ""),
        question.get("code", ""),
        question.get("answer", ""),
        question.get("analysis", ""),
        " ".join(question.get("options", [])),
    ]
    return "\n".join(str(part) for part in parts if part)


def parse_json_object(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
    match = re.search(r"\{.*\}", content, flags=re.S)
    if match:
        content = match.group(0)
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("模型输出 JSON 顶层必须是对象。")
    return parsed


def safe_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.75
    return round(max(0.0, min(number, 1.0)), 3)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    """Write complete JSON to a sibling temporary file, then publish atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def validate_mapping_integrity(
    questions: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    graph: dict[str, Any],
) -> dict[str, Any]:
    """Reject mapping output that references stale graph IDs before publication."""
    graph_ids = {str(node.get("id", "")) for node in graph.get("nodes", []) if isinstance(node, dict)}
    question_ids = [str(question.get("question_id", "")) for question in questions]
    mapping_ids = [str(mapping.get("question_id", "")) for mapping in mappings]
    invalid_links: list[dict[str, str]] = []
    unmapped: list[str] = []
    missing_primary: list[str] = []
    for mapping in mappings:
        question_id = str(mapping.get("question_id", ""))
        links = [link for link in mapping.get("links", []) if isinstance(link, dict)]
        if not links:
            unmapped.append(question_id)
        if links and not any(link.get("role") == "primary" for link in links):
            missing_primary.append(question_id)
        for link in links:
            target = str(link.get("knowledge_node_id", ""))
            if target not in graph_ids:
                invalid_links.append({"question_id": question_id, "knowledge_node_id": target})
    valid = (
        len(question_ids) == len(set(question_ids))
        and set(question_ids) == set(mapping_ids)
        and len(mapping_ids) == len(set(mapping_ids))
        and not invalid_links
        and not unmapped
        and not missing_primary
    )
    return {
        "valid": valid,
        "question_count": len(question_ids),
        "mapping_count": len(mapping_ids),
        "missing_mapping_question_ids": sorted(set(question_ids) - set(mapping_ids)),
        "unexpected_mapping_question_ids": sorted(set(mapping_ids) - set(question_ids)),
        "invalid_knowledge_node_references": invalid_links,
        "unmapped_question_ids": unmapped,
        "missing_primary_question_ids": missing_primary,
    }


def build_report(
    questions_path: Path,
    graph_path: Path,
    files: MappingFiles,
    mappings: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    method_counts: dict[str, int] = {}
    unmapped = 0
    total_links = 0
    primary_links = 0
    llm_errors: dict[str, str] = {}
    unresolved_gold_items: list[dict[str, Any]] = []

    for mapping in mappings:
        method = mapping.get("method", "unknown")
        method_counts[method] = method_counts.get(method, 0) + 1
        links = mapping.get("links", [])
        total_links += len(links)
        if not links:
            unmapped += 1
        for link in links:
            if link.get("role") == "primary":
                primary_links += 1
        if mapping.get("llm_error"):
            llm_errors[mapping["question_id"]] = mapping["llm_error"]
        for item in mapping.get("unresolved_gold_items", []):
            unresolved_gold_items.append({"question_id": mapping.get("question_id"), **item})

    return {
        "schema_version": "programming_kg_question_mapping_v3",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_questions": str(questions_path),
        "input_graph": str(graph_path),
        "output_links": str(files.links),
        "course_scope": args.course_id or "all_courses",
        "verified_answer_context_enabled": bool(args.use_verified_answer_context),
        "question_count": len(mappings),
        "total_link_count": total_links,
        "primary_link_count": primary_links,
        "unmapped_question_count": unmapped,
        "method_counts": method_counts,
        "provider": "none" if args.no_llm else args.provider,
        "model": args.model or ("none" if args.no_llm else PROVIDER_CONFIGS[args.provider]["model"]),
        "max_links_per_question": args.max_links,
        "llm_strategy": "ambiguous_only" if not args.llm_all else "all_questions",
        "llm_errors": llm_errors,
        "unresolved_gold_item_count": len(unresolved_gold_items),
        "unresolved_gold_items": unresolved_gold_items,
        "quality_policy": (
            "人工金标准优先；新题最多 3 个考点；仅来源验证且答案完整的正确选项可辅助召回；"
            "完整选项仅低权重参与主题召回；否定题的正确选项不参与高权重召回；"
            "候选不准确时允许留空进入复核。"
        ),
        "optional_mapping_metadata_policy": QUESTION_MAPPING_METADATA_POLICY,
        "metadata_added": bool(args.add_metadata),
    }


def split_mappings_for_formal_import(
    questions: list[dict[str, Any]], mappings: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """只发布具有至少一条 primary 考察关系的题目，其余保留给人工复核。"""
    question_by_id = {str(item.get("question_id", "")): item for item in questions if isinstance(item, dict)}
    formal_mappings = [
        mapping
        for mapping in mappings
        if isinstance(mapping, dict)
        and any(str(link.get("role", "")) == "primary" for link in mapping.get("links", []) if isinstance(link, dict))
    ]
    formal_ids = {str(mapping.get("question_id", "")) for mapping in formal_mappings}
    formal_questions = [question for question in questions if str(question.get("question_id", "")) in formal_ids]
    review = [
        {
            "question_id": str(mapping.get("question_id", "")),
            "reason": "题目答案已通过来源与完整性校验，但未形成可信的 primary 知识点映射。",
            "question": question_by_id.get(str(mapping.get("question_id", "")), {}),
            "mapping": mapping,
        }
        for mapping in mappings
        if str(mapping.get("question_id", "")) not in formal_ids
    ]
    return formal_questions, formal_mappings, review


def add_optional_mapping_metadata(mappings: list[dict[str, Any]]) -> None:
    """为新一轮映射补充教学分析字段；历史映射默认保持原样。"""
    role_weights = QUESTION_MAPPING_METADATA_POLICY["role_weights"]
    for mapping in mappings:
        for link in mapping.get("links", []):
            if not isinstance(link, dict):
                continue
            role = str(link.get("role", "secondary"))
            link["role_weight"] = role_weights.get(role, role_weights["secondary"])
            link.setdefault("mapping_status", "draft")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第五阶段 B：习题到知识点自动映射。")
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS, help="标准习题 questions.json 路径")
    parser.add_argument("--graph", default=DEFAULT_GRAPH, help="standard_graph.json 路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")
    parser.add_argument(
        "--course-id",
        default=None,
        help="课程中心化图谱的课程根 ID；指定后只允许映射到该课程的本地知识节点",
    )
    parser.add_argument(
        "--use-verified-answer-context",
        action="store_true",
        help="选择题仅使用已通过来源和完整性审核的正确选项参与召回；不会读取干扰项",
    )
    parser.add_argument("--provider", default="qwen", choices=["qwen", "deepseek"], help="LLM 提供方")
    parser.add_argument("--model", default=None, help="模型名称，默认 qwen-plus-2025-07-28/deepseek-chat")
    parser.add_argument("--base-url", default=None, help="兼容 OpenAI Chat Completions 的接口地址")
    parser.add_argument("--no-llm", action="store_true", help="只用规则映射，不调用 API")
    parser.add_argument("--timeout", type=int, default=60, help="API 超时时间，单位秒")
    parser.add_argument("--retries", type=int, default=2, help="API 失败重试次数")
    parser.add_argument("--no-cache", action="store_true", help="不使用 API 缓存")
    parser.add_argument("--llm-all", action="store_true", help="对全部题目调用模型；默认只处理候选接近的歧义题目")
    parser.add_argument("--max-links", type=int, default=5, help="每道题最多映射几个知识点")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 道题，0 表示全部")
    parser.add_argument(
        "--add-metadata",
        action="store_true",
        help="为本次新生成的链接写入 role_weight 和 mapping_status；默认保持历史字段不变",
    )
    parser.add_argument(
        "--split-unmapped-for-review",
        action="store_true",
        help="将无可信 primary 映射的题目写入复核清单，仅发布可安全入库的题目与链接",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    questions_path = Path(args.questions)
    graph_path = Path(args.graph)
    output_dir = Path(args.output_dir)
    files = MappingFiles(
        links=output_dir / "question_knowledge_links.json",
        report=output_dir / "question_mapping_report.json",
        cache_dir=output_dir / "mapping_cache",
        mapped_questions=output_dir / "mapped_questions.json",
        review=output_dir / "question_mapping_review.json",
    )

    questions = load_json(questions_path)
    graph = load_json(graph_path)
    if not isinstance(questions, list):
        raise ValueError("questions.json 顶层必须是数组。")
    if not isinstance(graph, dict):
        raise ValueError("standard_graph.json 顶层必须是对象。")
    if args.course_id:
        course_exists = any(
            isinstance(node, dict) and str(node.get("id", "")) == args.course_id and node.get("type") == "Course"
            for node in graph.get("nodes", [])
        )
        if not course_exists:
            raise ValueError(f"图谱中不存在课程节点：{args.course_id}")
    if args.limit > 0:
        questions = questions[: args.limit]

    llm_client = None
    if not args.no_llm:
        llm_client = LLMClient(
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            timeout=args.timeout,
            retries=args.retries,
            cache_dir=files.cache_dir,
            use_cache=not args.no_cache,
        )

    mapper = QuestionMapper(
        graph,
        llm_client=llm_client,
        max_links=args.max_links,
        llm_ambiguous_only=not args.llm_all,
        course_id=args.course_id,
        use_verified_answer_context=args.use_verified_answer_context,
    )
    mappings: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        print(f"[{index}/{len(questions)}] 映射 {question['question_id']}")
        mappings.append(mapper.map_question(question))

    if args.add_metadata:
        add_optional_mapping_metadata(mappings)
    report = build_report(questions_path, graph_path, files, mappings, args)
    integrity = validate_mapping_integrity(questions, mappings, graph)
    report["integrity_check"] = integrity
    if args.split_unmapped_for_review:
        formal_questions, formal_mappings, review = split_mappings_for_formal_import(questions, mappings)
        formal_integrity = validate_mapping_integrity(formal_questions, formal_mappings, graph)
        report["formal_import_partition"] = {
            "enabled": True,
            "formal_question_count": len(formal_questions),
            "review_question_count": len(review),
            "formal_questions": str(files.mapped_questions),
            "formal_links": str(files.links),
            "review": str(files.review),
            "formal_integrity_check": formal_integrity,
        }
        write_json(files.review, review)
        write_json(files.mapped_questions, formal_questions)
        write_json(files.links, formal_mappings)
    write_json(files.report, report)
    if not integrity["valid"] and not args.split_unmapped_for_review:
        raise ValueError(
            "题目映射完整性校验失败；已写入报告但未发布 links："
            f"{json.dumps(integrity, ensure_ascii=False)}"
        )
    if not args.split_unmapped_for_review:
        write_json(files.links, mappings)

    print(f"习题数量：{len(mappings)}")
    print(f"映射关系数量：{report['total_link_count']}")
    print(f"未映射习题数：{report['unmapped_question_count']}")
    print(f"映射结果：{files.links}")
    if args.split_unmapped_for_review:
        print(f"可入库题库：{files.mapped_questions}")
        print(f"映射复核清单：{files.review}")
    print(f"映射报告：{files.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
