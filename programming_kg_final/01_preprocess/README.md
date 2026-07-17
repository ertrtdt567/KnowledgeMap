# 01 资料预处理

入口：`../src/preprocess_materials.py`

职责：读取 PPT/PPTX、PDF、DOCX 等课程资料，提取文本、过滤目录和页眉页脚等噪声，按语义和长度切分为带来源信息的 `clean_chunks.json`。

`outputs/` 保存最终五门课程实际采用的三组清洗结果：Java/Python/C++ 主课程组、数据结构、UML。文件采用 GZip 压缩，使用 `../tools/restore_artifacts.py` 恢复。

原始课程资料因版权、体积和隐私原因不进入 GitHub。

