# 实施计划

## 1. 平台复用、依赖与契约

1. 冻结 `D:\project\agent\examples` 的复用清单、Git 状态、关键哈希和既有测试结果，禁止在该目录写入。
2. 将最小 `testing_platform` 骨架迁入正式仓库，运行迁移兼容测试并确认无 `..\examples` 运行时依赖。
3. 完成三格式新增解析依赖 spike，记录许可证、中文保真及 Windows/Linux/Kylin 可用性。
4. 扩展现有需求模型、Schema Registry 和任务类型，固定版本兼容策略。
5. 用 Schema 测试固定各层输入输出及失败状态。

验证门：迁移前后既有测试一致、正式仓库无兄弟目录依赖、有效/无效 Schema 样例和依赖最小样本全部通过后再实现 Adapter。

## 2. 文档摄取

1. 实现输入清单和配置快照。
2. 依次实现 Markdown、DOCX、PDF Adapter 及对应测试。
3. 实现对象清单、解析失败报告和重复运行稳定性检查。

验证门：三格式等价样本均可回查来源，扫描页和嵌入对象失败不被静默丢弃。

## 3. 需求分析与核验

1. 复用 AgentGateway、Hermes Gateway、SkillRegistry、任务与 Artifact 边界，并保留导出/导入模式。
2. 新增独立 Requirement Analysis Workflow 和专用 Skill，不复用 `test-case-design` 的 plan/cases 输出作为 S1 答案。
3. 依次实现 Section Extractor、Consolidator、确定性核验和独立语义核验。
4. 生成需求、测试类型、歧义、冲突、核验和追溯交付物。

验证门：固定夹具覆盖多规则拆分、数值保真、跨段条件、重复、冲突和证据不足。

## 4. 评分与实验

1. 固定材料角色：总纲是项目主需求，MiniOrder 是校准集，`技术要求.docx` 是开发验证集，历史 XLSX/benchmark 是回归证据。
2. 建立三格式等价集，并用历史结果验证既有消费者兼容性。
3. 固定真值、匹配和部分正确规则，完成评分器与报告锁。
4. 先运行不计分预演，修复流程问题后冻结正式协议。
5. 取得合法的未见盲测材料后执行一次正式评估，不反复换会话追求成绩。

验证门：所有指标能追溯分子、分母和逐条匹配；锁定报告修改可被检测。

## 5. 最终质量检查

1. 运行单元、契约、端到端测试和编码审计。
2. 执行 MiniOrder 文件与锁定报告无漂移检查。
3. 执行 OpenSpec strict validation、Trellis check 和中文运行文档复现。

## 回滚点

- 新能力位于正式仓库的 `testing_platform` 模块及独立评估、产物目录，不修改 MiniOrder。
- 不修改 `D:\project\agent\examples`，迁移内容在正式仓库中形成唯一运行时来源。
- 任一阶段失败时保留诊断证据，从最近一个通过的验证门恢复。
- 不使用 `git reset --hard` 或覆盖既有实验文件。
