# S1 评估资产与历史回归边界

## 材料角色

机器可读角色清单位于 `evaluation/requirement-analysis/material-roles.json`，哈希验证由单元测试执行。项目建设基线、MiniOrder 校准集、《技术要求》开发集、历史 Markdown/XLSX 回归资产均明确禁止进入正式泛化成绩。正式材料尚未登记，状态是等待用户确认合法、独立且未参与开发调整的材料。

## 三格式等价集

`scripts/requirement_analysis_dependency_spike.py` 的 `create_samples` 生成语义相同的 Markdown、DOCX、PDF：数量范围、单价精度和订单查询三条规则一致。DOCX 固定核心属性和 ZIP 元数据，PDF 使用 invariant 模式；同一依赖版本重复初始化的三个文件字节哈希一致。

等价集只用于区分格式解析差异，不是模型语义真值。单元测试验证三种 IR 均能回读相同规则、来源可定位，并明确保留 DOCX 分页和 PDF 布局限制。

## 历史 XLSX 只读核对

只读检查的历史工作簿哈希为 `f32b4610fb44cc7854cc0bb0c3a82d83a5449b6cd757e6bfb2bb635d63ccd5bb`，包含：

- `测试方案`：13 行、2 列；
- `测试用例`：9 行、18 列，含需求编号/来源；
- `需求追踪矩阵`：9 行、7 列，含需求 ID、说明、覆盖用例和覆盖数；
- `填写说明`：9 行、2 列。

该工作簿证明旧链路能形成结构化追踪，不证明其中需求或用例正确。本轮未修改、重算或导出工作簿，也不向分析 Agent 提供其内容。

## 快速回归与正式评分的区别

`quick_regression` 延续旧工具的有限目标：检查预期编号、意外编号、来源缺失和禁止编造词。它不能衡量语义精确率、召回率、来源定位有效率或数值保真，结果不得作为正式成绩。

旧 `RequirementItem`、`ParsedRequirements 1.0` 和 `TestDesignPackage` 仍由兼容测试读取；S1 的 `2.0` 基线禁止静默降级，以免新来源与核验字段被旧消费者无声丢弃。
