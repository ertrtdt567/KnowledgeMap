# RDF 与正式发布复现说明

本目录保存生成 `v2026.07.18` 正式发布和 RDF 数据所需的源码副本。以下命令均从 `programming_kg_final` 目录运行。

## 文件

- `publish_formal_release.py`：从正式课程图、题库和映射生成不可变发布目录。
- `export_rdf.py`：将正式 JSON 导出为 Turtle、RDF/XML、验证报告和 SPARQL 查询。
- `run_sparql_validation.py`：实际执行 `validate_counts.sparql` 并保存 JSON/Markdown 结果。

## 重新生成正式发布

固定原发布时刻后，发布脚本可从发布前源图、题库和映射精确重建正式图谱：

```powershell
python tools\restore_artifacts.py --file 08_delivery\reproducibility_inputs\pre_release_graph.json.gz
python 08_delivery\reproducibility\publish_formal_release.py `
  --graph 08_delivery\reproducibility_inputs\pre_release_graph.json `
  --questions 08_delivery\reproducibility_inputs\source_questions.json `
  --mappings 08_delivery\reproducibility_inputs\source_mappings.json `
  --output-dir 08_delivery\reproduced_release `
  --generated-at 2026-07-17T18:45:52.797200+00:00
```

隔离复跑已得到图谱 SHA256 `791BA16A6B3B6DC04A71B28BC608C18ACDEAC51F344B08E6398666295971B1F8`，与正式发布完全一致。结构化记录见 `release_reproduction_report.json`。

## 重新导出 RDF

先恢复正式 JSON，再运行：

```powershell
python tools\restore_artifacts.py --file 08_delivery\standard_graph.json.gz
python 08_delivery\reproducibility\export_rdf.py `
  --graph 08_delivery\standard_graph.json `
  --output-dir 08_delivery\rdf\generated
```

## 执行 SPARQL 计数查询

```powershell
python 08_delivery\reproducibility\run_sparql_validation.py `
  --rdf 08_delivery\rdf\standard_graph.rdf `
  --query 08_delivery\rdf\validate_counts.sparql `
  --output-json 08_delivery\rdf\sparql_query_result.json `
  --output-md 08_delivery\rdf\sparql_query_result.md `
  --expected-nodes 2612 --expected-edges 6059
```

有 RDFLib 时脚本使用标准 RDFLib SPARQL 引擎；离线机器没有 RDFLib 时，使用仅支持本条计数查询的标准库回退执行器，并在结果文件中明确记录引擎名称。
