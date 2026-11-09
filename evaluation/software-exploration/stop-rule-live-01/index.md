# 停止规则单次实测证据索引

- `final-report.md`：组织侧最终结论、偏离、限制和最小建议。
- `protocol.md`、`freeze.json`、`freeze-lock.json`：运行前冻结材料。协议标题保留“候选”原字节，最终冻结状态以 freeze 为准，未事后改标题。
- `isolation.md`、`launch-instructions.md`、`test-agent-prompt.md`、`test-bundle.md`：隔离边界和完整初始输入；冻结文件哈希不代表平台实收明文逐字核验。
- `adjudications/runtime-audit.json`：独立逐调用目录、预算、通信及原 CLI 退出码/错误。
- `adjudications/checkpoints.json`：15 个可表达检查点及 1 个缺被动的人工裁决。
- `adjudications/notes.md`、`adjudications/lock-verification.json`：独立结论与原始证据核验。
- `quality-review.md`：按 Trellis 要求的独立质量复核。
- `results-lock.json`：最终交付精确字节清单；不覆盖原始报告锁。

统一运行证据根目录为 `artifacts/software-exploration/stop-rule-live-01/`：

- `run-01/raw-report.json`、`session.jsonl`、`tool-events.jsonl`、`capture-manifest.json`、`organizer-start.json`、`report-lock.json`：正式原始交付及先于评估的 5 项锁。
- `dispatch-session.jsonl`、`dispatch-manifest.json`、`dispatch-addendum.json`：单次派发、原说明与锁后勘误，均保留。
- `health-01/`：独立副本健康前置及其冻结原始轨迹，未提供给正式方。
- `organizer-cleanup/`、`organizer-finish.json`：锁后独立清理、残留前态、进程退出及程序/种子哈希；不计正式方表现。
- `pre-run-integrity.json`、`post-run-integrity.json`、`historical-lock-verification.json`：前后完整性核查及未提交工作区状态。

只读重核原审计入口：

```powershell
python -X utf8 scripts/audit_exploration_stop.py --runtime-audit evaluation/software-exploration/stop-rule-live-01/adjudications/runtime-audit.json --checkpoints evaluation/software-exploration/stop-rule-live-01/adjudications/checkpoints.json --output artifacts/software-exploration/stop-rule-live-01/new-stop-audit.json
```

当前完整目录含不受原 CLI 支持的真实通信调用，预期明确拒绝，不能把退出 2 当产品失败或停止通过。不要修改/删除真实调用来求得通过，不要覆盖已锁输出，不要通过本索引重新启动正式 GUI 实验。
