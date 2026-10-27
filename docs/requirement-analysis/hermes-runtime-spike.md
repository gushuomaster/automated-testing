# Hermes 需求分析运行时验证

## 结论

2026-10-22 通过正式仓库的 `HermesAgentGateway`、`SkillRegistry` 和现有 Hermes Profile 解析入口完成一次最小结构化需求响应。返回值通过 `RequirementCandidate` 的 Pydantic/JSON Schema 约束，证明首版可以复用 Hermes 作为可替换 Agent 运行时。

这不是需求解析质量验收：输入只有一条人工构造规则，没有测试召回率、复杂文档、冲突归并或独立核验能力。

## 冻结信息

- `hermes-agent`: 0.11.0
- Git 提交：`5e68503d2f90aa2822494c910809eae1c3895238`
- Provider：`minimax-cn`
- Model：`MiniMax-M2.7`
- Skill：`requirement-analysis 1.0.0`
- 调用入口：`scripts/verify_hermes_requirement_contract.py` → `create_hermes_agent_gateway` → `HermesAgentGateway.run`
- 原始响应不写入报告；只记录内容 SHA-256、状态、模型和结构校验结果。

## 实测结果

- Hermes Profile `test-design-agent` 的路径解析成功；该历史测试设计 Profile 只用于验证 Profile 机制，没有用于正式需求响应，避免引入测试用例职责。
- 正式需求响应使用默认 Hermes 配置、临时系统提示、禁用 memory 和工具集的新 Agent 上下文。
- 项目 `configs/skills.yaml` 正确解析到仓库内 `skills/requirement-analysis/SKILL.md`。
- Agent 返回 `status=succeeded`，`structured_output_valid=true`，无结构错误。
- 机器可读证据：`artifacts/requirement-analysis/hermes-spike/result.json`。

## 运行依赖边界

验证时借用了既有只读环境 `D:\project\agent\examples\.venv` 中已经安装的 Hermes 包，但加载的是本仓库 `src/testing_platform` 代码、配置、Skill 和 Schema。正式项目不导入或读取 `..\examples`。Hermes 仍是外置、可替换的软依赖；固定提交已经记录，但本轮 `uv lock` 获取该 Git 依赖连续超时，故没有把未锁定依赖写入 `pyproject.toml`。恢复条件是目标部署环境能安装上述提交，或项目提供经复核的内部 wheel/镜像。

## 限制

1. 现有默认 Hermes 配置属于当前机器，不是可移植部署资产；凭据没有复制进仓库或产物。
2. 真实调用可能在用户 Hermes 目录产生运行时会话日志；需求工作流自身禁用 memory，且本报告不读取这些历史内容。
3. Profile 机制可用不代表现有 `test-design-agent` 适合需求分析。需求分析使用独立 Skill 和临时上下文。
