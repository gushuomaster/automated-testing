# 最小设计与变更边界

行为缺口位于测试上下文的动作后决策与结束执行，并非MiniOrder业务或UFO dispatcher。当前没有可直接修复的Sky循环函数；选定指令+只读审计，保留物理强制停止缺口。

新增`docs/software-exploration/stop-decision-card.md`：不给业务路径/控件ID/答案，只给通用分支，明确终止优先于测试方清理；固定为下一次授权实验可引用的候选输入，不改旧bundle。

新增`scripts/audit_exploration_stop.py`与对应单元测试：直接读取已由评估方核验的runtime-audit.tool_calls作为规范化调用目录，检查点独立提供input/immediate/passive编号、outcome与理由。复用该目录避免另写JS解析器或NLP判定。脚本验证目录顺序、输入数与方法类别、引用及回读配对；主动后未决到被动确认前有输入也记偏离，未决被动结果后的所有输入含清理列出，首个截止点单列。focus-only例外与已确认结果不触发终止。输出只对所审检查点与提供目录负责，人工语义和目录完整性仍是外部前置；不能把无偏离输出当全协议PASS。

新增`evaluation/software-exploration/stop-rule-calibration-01/`保存候选指令副本/回归检查点/报告/独立审查/锁；产物在`artifacts/software-exploration/stop-rule-calibration-01/`。读取历史记录用于development/regression，不向正式测试方派发，不改历史锁文件。

状态语义：CONFIRMED允许继续；UNRESOLVED要求一次纯被动复核，若被动仍UNRESOLVED则后续输入全部违规；FOCUS_METADATA_ONLY允许另一允许行为核验，不能把它当已解决或全协议通过。审计不重判产品行为，不修改权重或报告。

验证：真实旧轮2未决+2已解决案例、合成已停止及清理续输等单测；原锁哈希核验。独立check复核输入边界和结论。不使用GUI，不测试新Agent运行，不据离线通过宣称可靠性。
