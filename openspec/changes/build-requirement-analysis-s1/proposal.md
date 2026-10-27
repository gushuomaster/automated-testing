# 第一阶段需求解析能力提案

## Why

`CS-Autonomous-Testing-Framework-v0.1.md` 将需求理解定义为自主测试流程的第一阶段，但 MiniOrder 实验和既有测试用例生成结果尚未独立证明需求资料能被完整解析、准确拆解并形成可追溯的需求基线。`D:\project\agent\examples` 已存在可复用的 `testing_platform`、Agent 端口、Hermes 适配和 Skill 机制，本变化应在这些已验证边界上补齐需求分析能力，而不是重复建设一套平行框架。

## What Changes

- 新增 DOCX、Markdown、PDF 三种输入格式的确定性解析入口，将标题、段落、表格、页面和解析失败区域规范化为统一文档片段。
- 复用现有 `testing_platform` 分层、Pydantic 模型、AgentGateway、Hermes Gateway、SkillRegistry、任务与产物边界；Hermes 仅作为首版可替换 Agent 运行时。
- 扩展已有 `ParsedRequirements`、`SourceReference` 和 Schema Registry，新增独立 Requirement Analysis Workflow 与专用需求分析 Skill，不再把需求提取与测试用例生成绑定在同一步骤。
- 新增原子需求提取能力，识别测试对象、功能、性能、接口、边界、安全、约束和异常规则，并保留数值、单位、条件和例外。
- 新增测试类型推荐，但本阶段不生成测试项和测试用例。
- 新增逐条来源追溯、歧义与冲突记录、明示/推导/假设区分和置信度。
- 对模型返回的确定性来源证据错误提供一次受限、可审计的修复机会，包括不存在或越过当前窗口的片段标识，以及有效片段标识下不连续或错配的摘录；修复只能调整来源证据，修复后仍无效则按校验失败终止，不猜测、删除证据或静默替换来源。
- 归并、语义核验和修订阶段仅向模型提供候选引用对应的去重来源片段；完整 Document IR 留在本地用于确定性校验。
- 在 AgentGateway 调用前限制序列化阶段输入大小；超限时明确失败，不截断、不静默删除来源，也不发起模型调用。
- 对可能产生大型输出的归并和语义核验按冻结上限分块执行；跨块 Agent 只返回合并、冲突和术语关系操作，本地确定性组装完整基线与核验结果，避免单次响应承担整个大型 JSON。
- 新增确定性检查与独立语义核验，保留初始提取和核验结果，不用核验结果覆盖原始输出。
- 新增校准集、开发验证集、格式等价集和正式盲测集的评估协议；正式验收前冻结真值、匹配规则、预算和统计口径。
- 明确材料角色：`CS-Autonomous-Testing-Framework-v0.1.md` 是项目建设需求基线，MiniOrder 中文需求是校准样本，`技术要求.docx` 是开发验证样本，正式盲测另用未参与开发的独立资料。
- 曾用于诊断并直接推动实现或提示调整的正式样本必须降级为回归材料，不得继续计入后续正式泛化成绩；新的正式盲测必须重新选择未参与开发的合法材料并在运行前冻结真值和规则。
- 历史经验补全默认关闭；XLSX、CSV、PPT、PPTX、PNG、JPG、BMP 等格式扩展留到后续变化。

## Capabilities

### New Capabilities

- `document-ingestion`: 冻结输入文件，将 DOCX、Markdown 和 PDF 内容转换为带稳定来源位置、顺序和解析状态的统一文档片段，并显式报告未解析区域。
- `requirement-analysis`: 从统一文档片段提取、合并并核验原子需求，生成测试类型建议、歧义、冲突、来源追溯和可评估的结构化结果。

### Modified Capabilities

无。当前仓库没有已发布的需求解析规格。

## Impact

- 在正式仓库中复用或迁移 `D:\project\agent\examples` 已验证的接口与模块，并记录来源；不得让正式运行依赖可变的兄弟目录，也不得覆盖该目录中的用户未提交修改。
- 扩展测试系统自身的需求模型、文档读取、工作流、Skill、Schema 注册和结构化输出契约；来源引用修复须保留原始与修复响应并计入运行预算；MiniOrder 业务实现、需求和既有实验成绩不变。
- 后续需要选择并验证 DOCX、Markdown、PDF 解析依赖以及可替换的模型调用适配层。
- 首版复用 Hermes 配置、Profile、Skill 和模型调用能力，但需求解析核心只依赖 AgentGateway，允许后续替换为 Codex、OpenAI-compatible API 或经批准的本地模型。
- 需要新增独立评估资产和盲测运行约束，但评估真值不得暴露给正式分析 Agent。
- 本变化不引入 GUI 执行器、Windows 自动化框架、完整 B/S 管理平台或历史知识库。
