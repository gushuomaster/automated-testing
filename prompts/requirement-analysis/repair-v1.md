# Requirement Repair v1

根据核验发现和 `sources` 中列出的去重来源片段，对锁定初始基线做至多一次修订，输出新的 `requirement-baseline/v1`。输入仅包含基线所引用的片段，不是完整文档。只能删除无来源内容、恢复数值与单位、补充已有来源、拆分错误归并或把无法成立的内容移入歧义；不得添加新业务规则。保留未受影响的编号和来源。禁止输出测试项或测试用例。

`parsed.schema_version` 为 `2.0` 时，每条保留或修订后的正式需求必须显式包含非空
`target`、`categories`、`description`、`expected_behavior`、数值范围为 0 至 1 的
`confidence` 和非空 `source_evidence`。每项来源必须从初始基线或输入文档原样保留
`path`、`sha256`、`segment_id` 和 `locator`，不得为压缩输出而省略、缩短或重建。

返回前检查 JSON 语法和 v2 必填字段完整，不得输出对象以外的文字。
