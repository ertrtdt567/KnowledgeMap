# 正式发布复现输入

本目录仅用于精确重建 `v2026.07.18`，不作为前端或 Neo4j 的正式输入。

## 输入文件

- `pre_release_graph.json.gz`：发布前源图，解压后 2,618 个节点、6,074 条关系，SHA256 为 `E2FACD80A065CC304D3982AC08D66A8719198B95A8DA2EBF5B3EF94EFBE8B6D8`。
- `source_questions.json`：45 道正式题目，SHA256 为 `87A8C086BF2AC70F6962965E0E364F0CD3A7938989F00CDCF08A09C016B9B761`。
- `source_mappings.json`：发布前题目映射，SHA256 为 `EBE735FEB4FBC9297972E04DBA50A6C63C3ABECDBB32CD47B01B30AB30940CC4`。

## 复现命令

```powershell
python tools\restore_artifacts.py --file 08_delivery\reproducibility_inputs\pre_release_graph.json.gz
python src\publish_formal_release.py `
  --graph 08_delivery\reproducibility_inputs\pre_release_graph.json `
  --questions 08_delivery\reproducibility_inputs\source_questions.json `
  --mappings 08_delivery\reproducibility_inputs\source_mappings.json `
  --output-dir 08_delivery\reproduced_release `
  --generated-at 2026-07-17T18:45:52.797200+00:00
```

生成的 `standard_graph_v2026.07.18.json` 应为 2,612 个节点、6,059 条关系，SHA256 应为 `791BA16A6B3B6DC04A71B28BC608C18ACDEAC51F344B08E6398666295971B1F8`。
