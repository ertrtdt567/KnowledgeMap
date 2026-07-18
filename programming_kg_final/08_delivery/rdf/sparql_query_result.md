# SPARQL 实际执行结果

- 执行时间（UTC）：2026-07-18T02:28:07.584291+00:00
- 执行引擎：stdlib limited SPARQL COUNT evaluator v1 (release query only)
- RDF SHA256：`6012131A5B3DF996C5077822C913A8A5478678614864F9F486DFC51B4DA3922B`
- 查询 SHA256：`3EB3198A80110DB11E48085C94D76BE9DC1E94D97E80E0B2EE700F5753E73D21`
- `node_count`：2612
- `relationship_count`：6059
- 与正式 JSON 计数一致：True

## 查询

```sparql
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX kg: <https://github.com/ertrtdt567/KnowledgeMap/kg/v2026.07.18/>
PREFIX type: <https://github.com/ertrtdt567/KnowledgeMap/kg/v2026.07.18/type/>

# 验证正式 RDF 中的节点与关系资源数量。
SELECT
  (COUNT(DISTINCT ?node) AS ?node_count)
  (COUNT(DISTINCT ?edge) AS ?relationship_count)
WHERE {
  OPTIONAL { ?node kg:nodeId ?nodeId . }
  OPTIONAL { ?edge rdf:type type:Relationship . }
}
```

说明：若执行引擎显示为 `stdlib limited`，表示本机未安装 RDFLib，
本次实际执行的是随发布包提供的计数查询，不代表支持任意 SPARQL。
