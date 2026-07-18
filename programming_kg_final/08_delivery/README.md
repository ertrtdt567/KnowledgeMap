# 08 最终交付

`standard_graph.json.gz` 是前端、Neo4j 和验收使用的唯一完整标准图谱，包含课程知识节点、全局核心概念、代码示例、正式习题及其映射关系。

- 版本：`v2026.07.18`
- 节点：2,612
- 关系：6,059
- 解压后 SHA256：`791BA16A6B3B6DC04A71B28BC608C18ACDEAC51F344B08E6398666295971B1F8`
- 正式审计：`formal_quality_audit.json`
- 发布清单：`release_manifest.json`
- RDF 正式数据、验证与实际查询结果：`rdf/`

恢复命令：

```powershell
python tools/restore_artifacts.py --file 08_delivery/standard_graph.json.gz
```

恢复后得到 `08_delivery/standard_graph.json`。提交给前端时应发送这份恢复后的文件，而不是第 3 或第 4 阶段的中间图。

`reproducibility_inputs/` 保存正式发布前的源图、题库和映射，仅用于精确复现发布过程，不是前端或 Neo4j 的正式输入。

仓库为控制重复大文件体积，将正式 JSON 保存为 `standard_graph.json.gz`；`release_manifest.json` 保留原始正式发布目录中的文件名与哈希。恢复出的 `standard_graph.json` 与清单所列正式图谱内容相同。
