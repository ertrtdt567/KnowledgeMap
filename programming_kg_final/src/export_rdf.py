"""Export a formal graph release as Turtle and RDF/XML, then validate counts.

No external RDF package is required.  RDF/XML is parsed again with the Python
standard library to prove that the exported entity and relationship resources
are well-formed and agree with the release JSON.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote


BASE_IRI = "https://github.com/ertrtdt567/KnowledgeMap/kg/v2026.07.18/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("图谱顶层必须是对象。")
    return payload


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def iri(segment: str, value: str) -> str:
    return BASE_IRI + segment + "/" + quote(value, safe="_-.")


def ttl_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


def xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def turtle(graph: dict[str, Any]) -> str:
    lines = [
        f"@prefix kg: <{BASE_IRI}> .",
        f"@prefix rel: <{BASE_IRI}relation/> .",
        f"@prefix type: <{BASE_IRI}type/> .",
        f"@prefix rdf: <{RDF}> .",
        f"@prefix rdfs: <{RDFS}> .",
        "",
    ]
    for node in graph.get("nodes", []):
        node_id = str(node["id"])
        node_type = str(node.get("type", "KnowledgeNode"))
        lines.extend([
            f"<{iri('entity', node_id)}> a <{iri('type', node_type)}> ;",
            f"  rdfs:label \"{ttl_escape(str(node.get('name', '')))}\" ;",
            f"  kg:nodeId \"{ttl_escape(node_id)}\" ;",
            f"  kg:nodeType \"{ttl_escape(node_type)}\" .",
            "",
        ])
    for edge in graph.get("edges", []):
        edge_id = str(edge["id"])
        source = str(edge["source"])
        target = str(edge["target"])
        relation = str(edge["type"])
        lines.extend([
            f"<{iri('entity', source)}> <{iri('relation', relation)}> <{iri('entity', target)}> .",
            f"<{iri('edge', edge_id)}> a <{iri('type', 'Relationship')}> ;",
            f"  rdf:subject <{iri('entity', source)}> ;",
            f"  rdf:predicate <{iri('relation', relation)}> ;",
            f"  rdf:object <{iri('entity', target)}> ;",
            f"  kg:edgeId \"{ttl_escape(edge_id)}\" .",
            "",
        ])
    return "\n".join(lines)


def rdf_xml(graph: dict[str, Any]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<rdf:RDF xmlns:rdf="{RDF}" xmlns:rdfs="{RDFS}" xmlns:kg="{BASE_IRI}" xmlns:rel="{BASE_IRI}relation/" xmlns:type="{BASE_IRI}type/">',
    ]
    for node in graph.get("nodes", []):
        node_id = str(node["id"])
        node_type = str(node.get("type", "KnowledgeNode"))
        lines.extend([
            f'  <rdf:Description rdf:about="{iri("entity", node_id)}">',
            f'    <rdf:type rdf:resource="{iri("type", node_type)}"/>',
            f'    <rdfs:label>{xml_escape(str(node.get("name", "")))}</rdfs:label>',
            f'    <kg:nodeId>{xml_escape(node_id)}</kg:nodeId>',
            f'    <kg:nodeType>{xml_escape(node_type)}</kg:nodeType>',
            '  </rdf:Description>',
        ])
    for edge in graph.get("edges", []):
        edge_id = str(edge["id"])
        source = str(edge["source"])
        target = str(edge["target"])
        relation = str(edge["type"])
        lines.extend([
            f'  <rdf:Description rdf:about="{iri("entity", source)}">',
            f'    <rel:{relation} rdf:resource="{iri("entity", target)}"/>',
            '  </rdf:Description>',
            f'  <rdf:Description rdf:about="{iri("edge", edge_id)}">',
            f'    <rdf:type rdf:resource="{iri("type", "Relationship")}"/>',
            f'    <rdf:subject rdf:resource="{iri("entity", source)}"/>',
            f'    <rdf:predicate rdf:resource="{iri("relation", relation)}"/>',
            f'    <rdf:object rdf:resource="{iri("entity", target)}"/>',
            f'    <kg:edgeId>{xml_escape(edge_id)}</kg:edgeId>',
            '  </rdf:Description>',
        ])
    lines.append('</rdf:RDF>')
    return "\n".join(lines) + "\n"


def validate_rdf_xml(path: Path, expected_nodes: int, expected_edges: int) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    descriptions = root.findall(f"{{{RDF}}}Description")
    entity_uris = {
        item.attrib.get(f"{{{RDF}}}about", "")
        for item in descriptions
        if "/entity/" in item.attrib.get(f"{{{RDF}}}about", "")
    }
    entity_count = len(entity_uris)
    relationship_type = iri("type", "Relationship")
    relationship_count = sum(
        1
        for item in descriptions
        if any(child.tag == f"{{{RDF}}}type" and child.attrib.get(f"{{{RDF}}}resource") == relationship_type for child in item)
    )
    return {
        "parser": "xml.etree.ElementTree",
        "rdf_xml_well_formed": True,
        "entity_resource_count": entity_count,
        "relationship_resource_count": relationship_count,
        "expected_node_count": expected_nodes,
        "expected_edge_count": expected_edges,
        "passed": entity_count == expected_nodes and relationship_count == expected_edges,
    }


def sparql() -> str:
    return f"""PREFIX rdf: <{RDF}>
PREFIX kg: <{BASE_IRI}>
PREFIX type: <{BASE_IRI}type/>

# 验证正式 RDF 中的节点与关系资源数量。
SELECT
  (COUNT(DISTINCT ?node) AS ?node_count)
  (COUNT(DISTINCT ?edge) AS ?relationship_count)
WHERE {{
  OPTIONAL {{ ?node kg:nodeId ?nodeId . }}
  OPTIONAL {{ ?edge rdf:type type:Relationship . }}
}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="导出正式图谱为 Turtle 与 RDF/XML。")
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    graph = load_json(args.graph)
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    ttl_path = args.output_dir / "standard_graph.ttl"
    rdf_path = args.output_dir / "standard_graph.rdf"
    atomic_write(ttl_path, turtle(graph))
    atomic_write(rdf_path, rdf_xml(graph))
    validation = validate_rdf_xml(rdf_path, len(nodes), len(edges))
    validation.update({"graph": str(args.graph.resolve()), "ttl": ttl_path.name, "rdf": rdf_path.name, "namespace": BASE_IRI})
    atomic_write_json(args.output_dir / "rdf_validation_report.json", validation)
    atomic_write(args.output_dir / "validate_counts.sparql", sparql())
    if not validation["passed"]:
        raise ValueError(f"RDF 验证失败：{validation}")
    print(f"Turtle：{ttl_path}")
    print(f"RDF/XML：{rdf_path}")
    print(f"RDF 验证通过：{validation['passed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
