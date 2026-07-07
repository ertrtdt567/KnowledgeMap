# 第二部分：实体与关系抽取

`extract_graph.py` 用于从第一部分生成的 `clean_chunks.json` 中抽取知识图谱实体和关系。

## 实体类型

当前 Schema 包括：

- `ProgrammingParadigm`
- `OOPConcept`
- `CodeStructure`
- `SyntaxRule`
- `ProgrammingLanguage`
- `CodeExample`
- `Exercise`
- `ErrorPattern`
- `Skill`

## 关系类型

当前关系类型包括：

- `belongs_to_paradigm`
- `part_of`
- `prerequisite_of`
- `implemented_in`
- `has_syntax`
- `expresses_concept`
- `has_code_structure`
- `demonstrates`
- `uses_syntax`
- `contains_structure`
- `assesses`
- `requires_skill`
- `may_cause`
- `confused_with`
- `equivalent_to`
- `differs_from`
- `inherits_from`
- `implements_interface`

## 输出

会生成：

- `entities.json`
- `relations.json`
- `extraction_report.json`
- `api_cache/`

`extraction_report.json` 包含 Schema 合法性、类型一致性、置信度分布、失败记录等质量统计。
