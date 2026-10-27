# 需求分析执行契约

## 1. Scope / Trigger

当修改 `testing_platform` 的文档摄取、需求提取、来源修复、分块归并、语义核验、正式运行或评分逻辑时，必须遵守本契约。其目的，是防止模型输出错误被静默修补、评估答案泄漏、冻结后改规则以及部分成功被误报为正式通过。

## 2. Signatures

正式或预演运行统一通过：

```powershell
python scripts/run_requirement_prerun.py <input> `
  --role <calibration|development|formal> `
  --output-root <artifact-root> `
  --timeout-seconds <positive-int> `
  --max-turns <positive-int> `
  --max-output-tokens <positive-int> `
  --max-agent-calls <positive-int> `
  --max-input-tokens-total <positive-int> `
  --max-output-tokens-total <positive-int> `
  --max-window-chars <positive-int> `
  --max-window-segments <positive-int> `
  --max-agent-input-chars <positive-int> `
  --max-consolidation-candidates <positive-int> `
  --max-verification-requirements <positive-int> `
  [--disable-revision]
```

核心评分签名：

```python
adjudicate(decisions, required_reviewer_ids, partial_credit) -> AdjudicationResult
score(truth, output, adjudication, role, report_sha256) -> ScoredEvaluation
```

## 3. Contracts

- 输入先形成 `input-manifest/v1` 和 `document-ir/v1`，原文件不得被修改。
- 每个模型阶段使用独立 Agent 上下文，工具与记忆关闭；真值、匹配规则、历史答案和评分日志不得进入 Agent 输入。
- `len(user_input) + len(system_context)` 必须在 Gateway 调用前检查；超过冻结上限时失败，不截断、不消耗调用或 token 预算。
- 来源修复每个提取窗口最多一次，只能修改 `source_evidence`，不得改变候选数量、顺序、语义、类别、条件或置信度。
- 归并和核验按冻结块大小执行。任一块失败即整次失败，不组装部分基线、不对部分结果评分。
- 正式运行必须先冻结材料、真值、规则、提示、Schema、实现、环境和预算哈希；运行目录只创建一次且不得覆盖。
- 原始运行先生成并验证 `report-lock/v1`，之后评估侧才能读取真值并评分。评估决定和结果另行锁定，不回写原始运行。
- 参与提示、实现或协议调整的材料必须降级为 `development` 或 `regression`，不得继续计入正式泛化成绩。

## 4. Validation & Error Matrix

| 条件 | 必须行为 |
| --- | --- |
| 不支持的输入格式 | 记录 `unsupported`，不标记解析成功 |
| 扫描页或不可解释对象 | 记录未知/失败片段，不推断为“无需求” |
| 未知或跨窗口 `segment_id` | 触发一次受限来源修复；仍失败则终止 |
| `excerpt` 不是连续原文 | 使用稳定来源错误码；不得本地猜测替换 |
| 修复响应改变业务字段 | 拒绝修复结果并终止，不发起第二次修复 |
| Agent 输入超过字符上限 | Gateway 调用前失败，预算计数保持不变 |
| 任一归并/裁决/核验块无效 | 整次运行失败，保留已完成证据 |
| token 或调用预算耗尽 | 明确记录预算失败，不重试扩大预算 |
| 报告锁漂移 | 禁止评分或继续恢复，保留原目录 |
| 两名复核者决定不一致 | 标记 `disputed`，正式结果不得通过 |
| 关键数值、单位、比较关系或条件改写 | 记录关键错误，正式结果不得通过 |

## 5. Good / Base / Bad Cases

- Good：41 条锁定输出经两个独立复核者一致裁决，报告锁无漂移，再由冻结评分器计算指标。
- Base：模型输出有来源支持，但一条输出合并两条可独立真值；只能匹配一条，另一条保持未匹配，不能提高召回。
- Bad：看到成绩后修改真值、匹配规则、预算或原始输出，再重算并覆盖旧报告。
- Bad：某个分块失败后丢弃该块，仅用成功块生成“部分正式成绩”。

## 6. Tests Required

- Adapter：三种格式、稳定片段 ID、未知对象、扫描页及重复运行。
- 来源修复：成功、仍无效、跨窗口、业务字段改写、预算耗尽和不得二次修复。
- 输入限制：超限不调用 Gateway、不记预算、不截断。
- 分块：全局编号、未知编号拒绝、重复消费拒绝、来源并集、每条需求恰好核验一次。
- 评分：双复核者、部分分、重复项、一对一匹配、类别分母、关键错误、锁哈希和正式角色门槛。
- 全范围门：`pytest`、`compileall`、OpenSpec strict、`uv lock --check`、UTF-8/JSON、历史锁和 MiniOrder 无漂移审计。

## 7. Wrong vs Correct

### Wrong

```python
# 模型引用错误时，按语义相似度静默替换来源并继续评分。
candidate.source_evidence = nearest_segments(candidate.description)
```

### Correct

```python
# 保留原始响应，使用当前窗口允许片段发起一次受限修复；
# 完整重校验失败则终止，原始和修复证据都进入报告锁。
repaired = repair_source_evidence_once(candidate, allowed_segments)
validate_candidate_source(repaired, allowed_segments)
```

