# Source Reference Repair v1

只修复当前提取窗口候选中的来源引用，输出完整的 `requirement-candidate/v1`。

输入只提供原候选、确定性来源校验错误，以及当前窗口合法片段的 `segment_id` 和原文。仅可修改 `requirements` 或 `ambiguities` 中的 `source_evidence`；不得修改、删除、新增或重排任何候选，不得改写需求陈述、条件、预期行为、分类、信息性质或置信度。

选择来源时只能使用 `valid_segments` 中明确列出的 `segment_id`，不得猜测、模糊匹配或引用窗口以外的片段。来源的 `excerpt` 如保留或填写，必须是对应 `text` 中包含标点和空白在内的连续原文。`path`、`sha256` 和 `locator` 将由系统依据合法 `segment_id` 做确定性恢复，不得通过修改其他字段规避校验。

无法从当前窗口确定正确来源时，仍按 Schema 返回原候选，不要删除候选或编造来源；系统会将再次校验失败明确记录为本窗口失败。
