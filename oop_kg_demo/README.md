# 面向对象编程知识图谱 Demo

本目录包含知识图谱构建 Demo 的前两部分代码：

- `part1_preprocess/`：多源教学材料预处理，将 PPT/PDF/TXT/JSON 习题清洗并切分为 `clean_chunks.json`。
- `part2_extract/`：实体与关系抽取，基于 `clean_chunks.json` 调用大模型 API 并进行 Schema 校验、去重和质量统计。

## 运行顺序

1. 先运行第一部分，生成清洗后的知识片段：

```powershell
python part1_preprocess/preprocess_materials.py --input input --output output/clean_chunks.json
```

2. 再运行第二部分，抽取实体和关系：

```powershell
python part2_extract/extract_graph.py --input output/clean_chunks.json --output-dir output/graph_extract --provider qwen --limit 20
```

其中 `--limit` 用于测试模式；去掉后会处理全部 chunk。

## API Key

通义千问 API Key 使用环境变量：

```powershell
[Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY", "你的API_KEY", "User")
```

DeepSeek 可使用：

```powershell
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "你的API_KEY", "User")
```
