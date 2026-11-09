# 原始报告格式裁决

## 裁决原则

S2-A、S2-B 原始报告已经按字节锁定。本记录只解释格式问题，不修改原始 JSON，不要求测试 Agent 重写，也不改变冻结评分口径。评分程序只读取能够无歧义解析的字段。

## 锁完整性

| 运行 | 原始报告 SHA-256 | 字节数 | 锁验证 |
| --- | --- | ---: | --- |
| S2-A | `24cfde3b6f51ddbfb6305cdbb434c4f33202f1d145dd993585fa09f6b2a6d310` | 35,640 | 通过 |
| S2-B | `adae9aab59e3dc9a83eb6b54fc81bf7e8c3376156e5e0789c637ae22a8ccbb0b` | 32,519 | 通过 |

“锁验证通过”仅表示 `report-lock.json` 的 `files` 条目与实际原始报告大小、SHA-256 一致。锁文件另有 `lock_sha256` 声明，但仓库没有其生成算法，因此评分器保留该值但明确标为未复算，不把它作为额外完整性结论。

## Schema 偏差

| 运行 | 错误数 | 构成 | 是否妨碍锁后裁决 |
| --- | ---: | --- | --- |
| S2-A | 54 | 根对象多出 `input_sha256` 1 项；52 个 `confidence` 使用 `high/medium` 等文字而非 0～1 数字；`summary` 为对象而非字符串 | 否 |
| S2-B | 53 | 根对象多出 `input_sha256` 1 项；52 个 `confidence` 使用文字而非 0～1 数字 | 否 |

两份报告都是合法 JSON，均包含唯一的 REQ-001～REQ-052，映射状态、路径、证据引用和预算字段可以确定性读取。`input_sha256` 还可与冻结输入包交叉核验，但因 Schema 禁止额外属性，仍按格式错误保留。

S2-A 的 `summary.status_counts` 写为 `MAPPED=22`、`UNREACHABLE=10`，而 52 个实际映射逐项统计为 `MAPPED=21`、`UNREACHABLE=11`。评分以逐项映射为准，不使用摘要计数代替原始记录。

## 根因与影响

正式提示只要求“符合提供的 Schema”，实际分发内容没有把 `confidence` 数值类型、`summary` 字符串类型和 `additionalProperties=false` 直接展开到测试 Agent 的可见提示中。两次独立运行出现同类置信度错误，支持这是输出契约传递不足，而不是单次 JSON 损坏。

影响范围：

- 不影响本轮需求映射、入口、路径、安全性和预算的人工裁决；
- 说明输出契约遵从能力未通过严格 Schema 验证；
- 后续轮次应把完整字段类型或一个不含业务答案的最小结构模板直接交给测试 Agent，并在锁定前只做机器可解析性检查，不允许改写语义答案。

可重复检查由 `scripts/evaluate_software_exploration_s2.py` 执行，逐项结果位于 `adjudications/s2-a.json` 和 `adjudications/s2-b.json`。
