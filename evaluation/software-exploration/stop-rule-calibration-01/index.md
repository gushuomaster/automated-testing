# 停止规则局部修正索引

本目录是development/regression，不是新正式探索。

- `validation-plan.md`：事前回归口径。
- `regression-checkpoints.json`：5个仅供开发/评估的人工语义检查点，不给正式测试方。
- `report.md`：修改、验证与结论边界。
- `quality-review.md`：独立质量审查。
- `verification.json`：原锁/编码与离线检查复核。
- `evidence-lock.json`：最终新文件证据锁，不覆盖历史记录。

通用候选指令位于`docs/software-exploration/stop-decision-card.md`；审计位于`scripts/audit_exploration_stop.py`。运行产物在`artifacts/software-exploration/stop-rule-calibration-01`。
