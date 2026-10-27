# 技术设计

## 设计来源

详细设计以 `openspec/changes/build-requirement-analysis-s1/design.md` 为准；对应行为契约位于该变化的 `document-ingestion` 和 `requirement-analysis` 规格。本文件只记录 Trellis 执行所需的关键边界。

## 架构边界

```text
Input Manifest
      -> Format Adapter
      -> Document IR v1
      -> Requirement Analysis Workflow
           -> Section Extractor
           -> Requirement Consolidator
           -> Deterministic + Semantic Verifier
      -> Structured Results
      -> Ground-truth Evaluator
```

- 复用 `D:\project\agent\examples` 中已有的 `testing_platform` 分层、需求模型、AgentGateway、Hermes Gateway、SkillRegistry、任务、Runner 和 Artifact 边界；只迁移本任务需要的最小模块，不修改该脏工作区。
- 正式实现归当前仓库管理，不通过 `..\examples` 导入或读取兄弟目录。
- Hermes 是首版可替换 Agent 运行时，不是需求分析框架；领域模型、Document IR、核验器和评分器只依赖稳定端口。
- 格式 Adapter、AgentGateway、核验器和评估器通过版本化契约解耦。
- 正式 Agent 只看输入包和输出规范；真值和评分保留在评估侧。
- 每次运行沿用平台 Artifact 边界写入独立运行目录，不得覆盖其他运行证据。
- 解析失败、模型失败、Schema 失败和评估失败使用不同状态和日志。

## 关键取舍

- 先以三种格式验证语义和追溯，避免十种格式同时引入失败变量。
- `CS-Autonomous-Testing-Framework-v0.1.md` 是项目主需求；MiniOrder、`技术要求.docx`、历史 XLSX/benchmark 分别是校准、开发验证和回归证据，不混入正式盲测成绩。
- 新增专用 Requirement Analysis Workflow 和 Skill，不复用要求生成 plan/cases 的历史 `test-case-design` 输出作为 S1 答案。
- PDF 首版只保证文本层；扫描页显式失败，OCR 留给后续扩展。
- 独立核验不读取真值，防止评估答案泄漏到需求生成。
- 模型通过现有 AgentGateway 接入；首版使用 Hermes Gateway，测试使用 Fake Gateway，必要时只替换 Adapter。
- 当前隔离是目录、上下文和提示边界，不声称为 OS 级安全沙箱。

### 来源元数据的确定性恢复

真实开发预演发现模型可能选中正确片段却机械抄错 SHA-256。提取后的来源规范化以有效 `segment_id` 为键，从 Document IR 恢复 `path`、`sha256` 和 `locator`，并保留原始响应及补正字段事件。这样避免让模型重复抄写确定性元数据成为流程单点，同时不修改需求语义。未知片段与非连续原文摘录仍拒绝；归并后的来源仍接受独立确定性核验。该机制已有回归测试和保存响应的离线验证，真实完整开发集预演仍待完成。

### 可分析片段边界

Section Extractor 只接收有文本且状态为 `parsed` 或 `partial` 的片段。`unknown`、`empty` 和无文本分页标记继续保留在完整 Document IR、解析问题及归并上下文中，用于失败和限制报告，但不作为业务需求文本交给模型解释。这样避免页码域、绘图内部字段或空段落产生伪需求，同时不隐去未解析内容。

归并与修订提示必须显式重申 v2 必填字段和完整来源元数据，因为兼容旧消费者的 Pydantic JSON Schema 对部分字段保留默认值，不能单独向模型表达 v2 条件约束。应用层严格校验仍是最终边界，提示不得用来放宽契约。

### 锁定失败运行的阶段恢复

当完整预演已经完成提取、归并和初始核验，仅在 `repair` 层失败时，允许创建新的运行目录继续 `repair → deterministic verify → verify-revised`。恢复入口先验证父报告锁、失败层和角色，并从父运行重建和重新校验 Document IR、候选、初始基线及初始语义核验；不重新调用模型执行已完成阶段，也不修改父目录。新运行记录父路径、父锁哈希、当前提示哈希、阶段输入/响应和独立报告锁。该入口只用于恢复可审计的同一预演，不改变正式盲测协议或评分口径。

## 风险控制

- 依赖选择先做许可证、中文和目标操作系统 spike。
- 迁移前冻结 `examples` 的 Git 状态、关键哈希和测试结果，迁移后运行兼容测试并检查无兄弟目录依赖。
- 扩展 `ParsedRequirements` 和 `SourceReference` 时使用 Schema 版本及旧消费者兼容测试。
- 数字、单位、来源引用同时使用确定性检查和语义核验。
- 所有模型响应、提示版本、重试和人工介入保留哈希与记录。
- 正式盲测输出先锁定再评分，争议通过新增裁决记录处理。

