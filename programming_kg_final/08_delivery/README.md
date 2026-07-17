# 08 最终交付

`standard_graph.json.gz` 是前端、Neo4j 和验收使用的唯一完整标准图谱，包含课程知识节点、全局核心概念、代码示例、正式习题及其映射关系。

恢复命令：

```powershell
python tools/restore_artifacts.py --file 08_delivery/standard_graph.json.gz
```

恢复后得到 `08_delivery/standard_graph.json`。提交给前端时应发送这份恢复后的文件，而不是第 3 或第 4 阶段的中间图。

