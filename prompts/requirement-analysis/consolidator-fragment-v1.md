# Requirement Fragment Consolidator v1

将当前候选块归并为一个完整但仅覆盖本块的 `requirement-baseline/v1` 片段，规则与 Requirement Consolidator v1 相同。

输出外层 `schema_version` 必须为 `requirement-baseline/v1`，内层 `parsed.schema_version` 必须明确为 `2.0`，不得使用兼容旧消费者的 `1.0`。

- 输入中的 `sources` 只包含本块候选引用的去重来源片段，不是完整文档。
- 只处理当前块内的重复、条件、冲突、歧义和测试类型推荐，不推测其他块内容。
- 每条正式需求必须保留完整 `path`、`sha256`、`segment_id` 和 `locator`；禁止新增候选以外来源。
- 使用块内唯一编号即可；系统会在校验后确定性转换为全局编号。
- 禁止输出测试计划、测试项、用例、步骤或答案。

保持输出紧凑、JSON 完整；不得依赖续写补全未闭合的对象。
