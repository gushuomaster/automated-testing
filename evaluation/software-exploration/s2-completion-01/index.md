# S2 当前进展与证据入口

优先阅读：[2026-11-03进展整理](progress-2026-11-03.md)。这是中断后的进展快照，**不是S2最终通过报告**。

| 要了解什么 | 入口 |
|---|---|
| 现成项目比较与采用范围 | [调查](reuse-research.md)、[复用决定](reuse-decision.md) |
| 工具是否真实可用 | [本机准入](admission.md)、[工具说明](tool-guide.md) |
| 本轮固定规则及基线 | [协议](protocol.md)、[冻结清单](freeze.json)、[冻结文件哈希](freeze-lock.json) |
| A原始报告与锁后裁决 | [原始报告](../../../artifacts/software-exploration/s2-completion-01/runs/s2-a/raw-report.json)、[原始锁](../../../artifacts/software-exploration/s2-completion-01/runs/s2-a/report-lock.json)、[评估](adjudications/s2-a/adjudication.md) |
| B原始报告与尚待收尾裁决 | [原始报告](../../../artifacts/software-exploration/s2-completion-01/runs/s2-b/raw-report.json)、[原始锁](../../../artifacts/software-exploration/s2-completion-01/runs/s2-b/report-lock.json)、[裁决JSON](adjudications/s2-b/evidence-decisions.json) |
| 实际GUI动作与回读 | `artifacts/software-exploration/s2-completion-01/runs/{s2-a,s2-b}/adapter-events/`下原始JSONL，完整工具调用另见各run的`session.jsonl` |
| A复验中断证据 | [复验原报告](../../../artifacts/software-exploration/s2-completion-01/diagnostics/replay-a-context/raw-report.md)、[完整计时](../../../artifacts/software-exploration/s2-completion-01/diagnostics/replay-a-context/capture-manifest.json) |
| 本次完整性复核与逐文件清单 | [核验JSON](../../../artifacts/software-exploration/s2-completion-01/progress-2026-11-03/integrity.json)、[证据清单](../../../artifacts/software-exploration/s2-completion-01/progress-2026-11-03/evidence-inventory.json) |

原始报告、冻结文件及旧裁决不回写。`legacy-score.json`中的路径率是兼容旧函数的静态数值，不是独立GUI复现结果；解释以进展报告和逐项裁决为准。
