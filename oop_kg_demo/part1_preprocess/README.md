# 第一部分：多源教学材料预处理

`preprocess_materials.py` 用于把原始教学材料统一处理成结构化知识片段。

## 输入

支持：

- `.pptx`
- `.ppt`
- `.pdf`
- `.txt`
- `.md`
- `.json` 习题

## 输出

输出 `clean_chunks.json`，每条 chunk 会保留：

- `chunk_id`
- `source_file`
- `source_type`
- `language`
- `chapter`
- `section`
- `content`
- `keywords`
- `material_role`
- `evidence_location`

## 作用

这一部分不直接抽取实体和关系，而是完成：

```text
原始材料 → 文本提取 → 去噪 → OOP 相关性过滤 → 知识片段切分 → clean_chunks.json
```

这为第二部分实体关系抽取提供标准化输入。
