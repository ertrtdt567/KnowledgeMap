# 06 习题处理与知识点映射

该阶段保证一条正式题目记录同时具有题面、与题面严格对应的答案、来源证据和知识点映射。

主要流程：

1. 使用 `parse_*`、`extract_inline_answer_pdf_questions.py` 解析不同格式习题。
2. 使用 `complete_question_answers.py` 和统一题库脚本核对答案完整性；无答案或证据不足题目进入审核列表。
3. `build_unified_verified_question_bank.py` 去重并生成正式题库。
4. `map_questions_to_knowledge.py` 仅向当前课程树中的真实知识点 ID 建立映射。
5. `build_frontend_complete_graph.py` 将通过审核的题目和映射合并进课程图。

`outputs/formal_precise_questions.json` 和 `formal_precise_question_knowledge_links.json` 是最终入图数据。

