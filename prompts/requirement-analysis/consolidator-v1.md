# Requirement Consolidator v1

将候选归并为 `requirement-baseline/v1`，其中 `parsed.schema_version` 必须为 `2.0`。

输入中的 `sources` 是候选引用所需的去重来源片段；结合候选来源元数据使用。不得假设收到完整文档。

- 等价规则合并并保留全部来源；条件或结果不同的关联规则不强行合并。
- 跨片段补全条件时引用所有支持片段，不能引入候选以外的片段。
- `parsed.schema_version` 为 `2.0` 时，每条正式需求必须显式包含非空 `target`、`categories`、
  `description`、`expected_behavior`、数值范围为 0 至 1 的 `confidence` 和非空
  `source_evidence`；这些字段不得因 JSON Schema 中存在兼容默认值而省略。
- 每条正式需求的每项 `source_evidence` 必须从候选原样复制 `path`、`sha256`、`segment_id`
  和 `locator`；不得为了压缩输出省略字段、缩短哈希或自行重建位置。
- 同一对象的数值、单位、范围、行为冲突必须保留双方需求并建立冲突记录，不自行裁决。
- 术语关系和资料缺口进入歧义；测试类型推荐与需求分开，须关联需求、说明理由和置信度。
- `trace_index` 按需求编号列出全部 `segment_id`，`failed_segments` 记录输入中未解析片段。
- 禁止输出测试计划、测试项、用例、步骤或答案。

保持输出紧凑；可选空值和空列表应省略，不要复述输入或 JSON Schema。返回前检查 JSON 语法完整，
不得出现重复冒号、缺少逗号、截断对象或对象以外的文字。
