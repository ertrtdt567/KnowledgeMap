# RDF 验证与复现说明

本目录保存 `v2026.07.18` RDF 的查询、验证报告和实际运行结果。对应源码位于仓库 `programming_kg_final/src/`。

## 文件

- `src/publish_formal_release.py`：从正式课程图、题库和映射生成不可变发布目录。
- `src/export_rdf.py`：将正式 JSON 导出为 Turtle、RDF/XML、验证报告和 SPARQL 查询。
- `src/run_sparql_validation.py`：实际执行 `validate_counts.sparql` 并保存 JSON/Markdown 结果。

## 重新导出 RDF

从 `programming_kg_final` 目录运行，先恢复正式 JSON，再导出 RDF：

```powershell
python tools\restore_artifacts.py --file 08_delivery\standard_graph.json.gz
python src\export_rdf.py `
  --graph 08_delivery\standard_graph.json `
  --output-dir 08_delivery\rdf\generated
```

## 执行 SPARQL 计数查询

```powershell
python src\run_sparql_validation.py `
  --rdf 08_delivery\rdf\generated\standard_graph.rdf `
  --query 08_delivery\rdf\generated\validate_counts.sparql `
  --output-json 08_delivery\rdf\generated\sparql_query_result.json `
  --output-md 08_delivery\rdf\generated\sparql_query_result.md `
  --expected-nodes 2612 --expected-edges 6059
```

有 RDFLib 时脚本使用标准 RDFLib SPARQL 引擎；离线机器没有 RDFLib 时，使用仅支持本条计数查询的标准库回退执行器，并在结果文件中明确记录引擎名称。
