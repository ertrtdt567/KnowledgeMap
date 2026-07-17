from __future__ import annotations

import argparse
import gzip
import shutil
from pathlib import Path


def restore(source: Path, overwrite: bool = False) -> Path:
    if source.suffix != ".gz":
        raise ValueError(f"仅支持 .gz 文件: {source}")
    target = source.with_suffix("")
    if target.exists() and not overwrite:
        raise FileExistsError(f"目标已存在，使用 --overwrite 覆盖: {target}")
    with gzip.open(source, "rb") as compressed, target.open("wb") as output:
        shutil.copyfileobj(compressed, output)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="恢复发布包中的 GZip JSON 产物。")
    parser.add_argument("--file", help="只恢复指定 .gz 文件；缺省时恢复发布包内全部 .gz。")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sources = [Path(args.file)] if args.file else sorted(root.rglob("*.gz"))
    for item in sources:
        source = item if item.is_absolute() else root / item
        print(f"已恢复: {restore(source, args.overwrite)}")


if __name__ == "__main__":
    main()

