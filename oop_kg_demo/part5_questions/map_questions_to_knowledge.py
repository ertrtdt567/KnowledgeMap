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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_QUESTIONS = "work/oop_kg_demo/output/question_mapping/questions.json"
DEFAULT_GRAPH = "work/oop_kg_demo/output/graph_normalized/standard_graph.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/question_mapping"

PROVIDER_CONFIGS = {
    "qwen": {
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus",
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
    "class": ["类"],
    "类": ["类"],
    "object": ["对象"],
    "对象": ["对象"],
    "new ": ["对象"],
    "属性": ["属性"],
    "变量": ["属性"],
    "field": ["属性"],
    "方法": ["方法"],
    "method": ["方法"],
    "void ": ["方法"],
    "封装": ["封装", "信息隐藏"],
    "信息隐藏": ["信息隐藏", "封装"],
    "private": ["封装", "信息隐藏", "属性"],
    "public": ["封装", "方法"],
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
    "消息": ["消息传递"],
    "消息传递": ["消息传递"],
}


@dataclass
class MappingFiles:
    links: Path
    report: Path
    cache_dir: Path


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
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.2 * attempt)
        raise RuntimeError(f"{self.provider} API 调用失败：{last_error}")


class QuestionMapper:
    """把一道习题映射到标准图谱中的知识节点。"""

    def __init__(self, graph: dict[str, Any], llm_client: LLMClient | None, max_links: int) -> None:
        self.graph = graph
        self.llm_client = llm_client
        self.max_links = max_links
        self.knowledge_nodes = self._load_knowledge_nodes(graph)
        self.name_to_node = {node["name"]: node for node in self.knowledge_nodes}

    def map_question(self, question: dict[str, Any]) -> dict[str, Any]:
        candidates = self.recall_candidates(question)
        if self.llm_client is None:
            links = self.rule_links(question, candidates)
            method = "rule"
            llm_error = ""
        else:
            try:
                links = self.llm_links(question, candidates)
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
        }

    def recall_candidates(self, question: dict[str, Any]) -> list[dict[str, Any]]:
        text = build_question_text(question).lower()
        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = {}

        for node in self.knowledge_nodes:
            name = node["name"]
            aliases = [name] + list(node.get("aliases", []))
            for alias in aliases:
                alias_text = str(alias).strip().lower()
                if alias_text and alias_text in text:
                    add_score(scores, evidence, name, 3.0, f"命中知识点名称/别名：{alias}")

        for keyword, names in KEYWORD_TO_KNOWLEDGE.items():
            keyword_lower = keyword.lower()
            if keyword_lower in text:
                for name in names:
                    if name in self.name_to_node:
                        add_score(scores, evidence, name, 2.0, f"命中编程特征：{keyword}")

        # 如果题目明显命中某个核心知识点，把图谱里的一跳邻居也带进候选，避免漏掉次要关系。
        expanded = expand_with_neighbors(scores, self.graph, self.name_to_node)
        for name, reason in expanded.items():
            add_score(scores, evidence, name, 0.8, reason)

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

    def rule_links(self, question: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        # 规则模式用于离线兜底，宁愿少连一点，也不要把低分邻居误当成确定关系。
        # 低分候选仍会保留在 candidates 里，供 LLM 模式进一步判断。
        strong_candidates = [candidate for candidate in candidates if candidate["score"] >= 3.0]
        if not strong_candidates and candidates:
            strong_candidates = candidates[:1]

        for index, candidate in enumerate(strong_candidates[: self.max_links]):
            role = "primary" if index < 2 and candidate["score"] >= 3.0 else "secondary"
            confidence = min(0.95, 0.45 + candidate["score"] / 8)
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

    def llm_links(self, question: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candidates:
            return []
        messages = build_prompt(question, candidates, self.max_links)
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
            links.append(
                {
                    "knowledge_node_id": candidate["knowledge_node_id"],
                    "knowledge_name": name,
                    "knowledge_type": candidate["knowledge_type"],
                    "role": role,
                    "confidence": safe_confidence(raw.get("confidence")),
                    "evidence": str(raw.get("evidence", "")).strip() or "LLM 根据题干、代码和候选知识点判断",
                    "rank": len(links) + 1,
                }
            )
            if len(links) >= self.max_links:
                break

        if not links:
            return self.rule_links(question, candidates)
        return links

    @staticmethod
    def _load_knowledge_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = graph.get("nodes", [])
        if not isinstance(nodes, list):
            raise ValueError("standard_graph.json 的 nodes 必须是数组。")
        result = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") in {"OOPConcept", "SyntaxRule", "ProgrammingLanguage", "ProgrammingParadigm"}:
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


def build_prompt(question: dict[str, Any], candidates: list[dict[str, Any]], max_links: int) -> list[dict[str, str]]:
    system = (
        "你是编程教育知识图谱专家。请只从候选知识点中选择本题真正考察的知识点，"
        "区分 primary 和 secondary，并输出严格 JSON。不要新增候选列表之外的知识点。"
    )
    user = {
        "question_id": question["question_id"],
        "type": question.get("type_label") or question.get("type"),
        "language": question.get("language"),
        "stem": question.get("stem"),
        "code": question.get("code"),
        "options": question.get("options", []),
        "answer": question.get("answer"),
        "analysis": question.get("analysis"),
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
            f"最多输出 {max_links} 个知识点",
            "至少输出 1 个 primary，除非题目完全无法判断",
            "knowledge_name 必须来自 candidates",
        ],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


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

    return {
        "schema_version": "oop_kg_question_mapping_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_questions": str(questions_path),
        "input_graph": str(graph_path),
        "output_links": str(files.links),
        "question_count": len(mappings),
        "total_link_count": total_links,
        "primary_link_count": primary_links,
        "unmapped_question_count": unmapped,
        "method_counts": method_counts,
        "provider": "none" if args.no_llm else args.provider,
        "model": args.model or ("none" if args.no_llm else PROVIDER_CONFIGS[args.provider]["model"]),
        "max_links_per_question": args.max_links,
        "llm_errors": llm_errors,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第五阶段 B：习题到知识点自动映射。")
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS, help="标准习题 questions.json 路径")
    parser.add_argument("--graph", default=DEFAULT_GRAPH, help="standard_graph.json 路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")
    parser.add_argument("--provider", default="qwen", choices=["qwen", "deepseek"], help="LLM 提供方")
    parser.add_argument("--model", default=None, help="模型名称，默认 qwen-plus/deepseek-chat")
    parser.add_argument("--base-url", default=None, help="兼容 OpenAI Chat Completions 的接口地址")
    parser.add_argument("--no-llm", action="store_true", help="只用规则映射，不调用 API")
    parser.add_argument("--timeout", type=int, default=60, help="API 超时时间，单位秒")
    parser.add_argument("--retries", type=int, default=2, help="API 失败重试次数")
    parser.add_argument("--no-cache", action="store_true", help="不使用 API 缓存")
    parser.add_argument("--max-links", type=int, default=5, help="每道题最多映射几个知识点")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 道题，0 表示全部")
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
    )

    questions = load_json(questions_path)
    graph = load_json(graph_path)
    if not isinstance(questions, list):
        raise ValueError("questions.json 顶层必须是数组。")
    if not isinstance(graph, dict):
        raise ValueError("standard_graph.json 顶层必须是对象。")
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

    mapper = QuestionMapper(graph, llm_client=llm_client, max_links=args.max_links)
    mappings: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        print(f"[{index}/{len(questions)}] 映射 {question['question_id']}")
        mappings.append(mapper.map_question(question))

    report = build_report(questions_path, graph_path, files, mappings, args)
    write_json(files.links, mappings)
    write_json(files.report, report)

    print(f"习题数量：{len(mappings)}")
    print(f"映射关系数量：{report['total_link_count']}")
    print(f"未映射习题数：{report['unmapped_question_count']}")
    print(f"映射结果：{files.links}")
    print(f"映射报告：{files.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
