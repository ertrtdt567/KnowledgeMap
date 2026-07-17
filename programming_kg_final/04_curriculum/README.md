# 04 课程树与课程中心图

入口：

- `../src/curriculum_catalog.py`
- `../src/enrich_curriculum_graph.py`
- `../src/build_course_centered_graph.py`

课程目录：`../config/programming_curriculum_v0_13_candidate_finalized.json`

该阶段将五门课分别组织为课程、知识单元、知识点层级，同时保留可被多门课复用的全局核心概念。课程间不是简单混成一团，也不是完全割裂，而是通过核心概念映射建立受控连接。

`course_centered_standard_graph.json.gz` 是加入习题前的最终课程知识图谱。

