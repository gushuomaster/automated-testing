# S2 软件探索冻结基线说明

- 被测软件：MiniOrder 正确基线的匿名副本，仅使用一份构建。
- 需求来源：MiniOrder 中文需求及 S1 已锁定校准基线。
- S2-A 输入：从原始需求逐条核验后的中性需求集合。
- S2-B 输入：S1 真实 `requirement-baseline/v1` 的中性交付包，语义和需求标识不变。
- UI 工具：Computer Use 的 UIA 文本路径，入口为 `mcp__node_repl__js + @oai/sky`。
- 已知限制：截图通道历史上可能超时；界面变化后第一次 UIA 树可能不完整；旧元素索引不可跨状态复用。
- 历史 MiniOrder 端到端报告不计入本轮 S2 成绩。
- 具体文件哈希、环境和预算见 `freeze.json` 与 `environment.json`。
