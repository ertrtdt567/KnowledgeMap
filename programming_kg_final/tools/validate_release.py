from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path):
    opener = gzip.open if path.suffix == ".gz" else Path.open
    if path.suffix == ".gz":
        with opener(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    with opener(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def main() -> None:
    parser = argparse.ArgumentParser(description="校验最终发布包的文件摘要和关键 JSON。")
    parser.add_argument("--skip-json", action="store_true", help="只校验摘要，不解析大 JSON。")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "SHA256SUMS.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for item in manifest["files"]:
        path = root / item["path"]
        if not path.exists():
            failures.append(f"缺失: {item['path']}")
            continue
        if path.stat().st_size != item["bytes"]:
            failures.append(f"大小不符: {item['path']}")
        if sha256(path) != item["sha256"]:
            failures.append(f"摘要不符: {item['path']}")

    if not args.skip_json:
        graph = load_json(root / "08_delivery" / "standard_graph.json.gz")
        nodes = graph.get("nodes") or graph.get("entities") or []
        edges = graph.get("edges") or graph.get("relations") or []
        if not nodes or not edges:
            failures.append("最终图谱缺少节点或关系")
        print(f"最终图谱: {len(nodes)} 个节点, {len(edges)} 条关系")

    if failures:
        raise SystemExit("\n".join(failures))
    print(f"发布包校验通过: {len(manifest['files'])} 个文件")


if __name__ == "__main__":
    main()

