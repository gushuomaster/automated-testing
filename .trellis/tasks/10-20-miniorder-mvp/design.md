# MiniOrder MVP 技术设计

## 架构

实现采用 `samples/MiniOrder/` 下的独立 .NET 8 WinForms solution：

- `MiniOrder.Core`：领域模型、校验、金额计算、编号、查询和 JSON 持久化。
- `MiniOrder.App`：只使用标准 WinForms 控件的中文桌面 UI。
- `MiniOrder.Verification`：不依赖第三方测试框架的命令行契约验证和 evaluator 重置入口。

权威技术决策见 `openspec/changes/build-miniorder-mvp/design.md`。本文件仅记录 Trellis 执行边界，避免两套规划产生不同实现。

## 数据流

```text
WinForms 输入
  -> Core 校验/计算
  -> 订单服务
  -> 显式运行数据目录中的原子 UTF-8 JSON 存储
  -> 查询投影
  -> WinForms DataGridView/状态信息
```

评估方在授予 AI GUI 权限前，通过独立验证程序重置运行数据目录。测试 AI 不获得源码目录、评估方工具目录或发行构建参数。

## 版本边界

发行构建必须显式指定 `Baseline`、`VariantA` 或 `VariantB`。变体通过编译期策略改变单一规则，运行时数据和配置中不存在变体开关。发布后统一使用 `MiniOrder.exe` 和相同可见版本信息。

## 输出边界

所有生成内容进入：

```text
artifacts/miniorder/distributions/
artifacts/miniorder/blackbox-run/
artifacts/miniorder/diagnostics/
```

源代码、文档和评估方资产留在各自仓库路径；生成目录不得提交。黑盒 staging 使用 allowlist，而不是依赖排除列表。

## 验证策略

1. 使用 Release 配置编译，并将警告视为错误。
2. 使用 Core 契约矩阵验证正确基线和两个单缺陷版本。
3. 验证重置哈希、目录隔离和黑盒 allowlist。
4. 使用 CUA 在真实 Windows 桌面完成 UIA 观察、输入、保存、查询、重启和结果确认。
5. 最终审核 AI 可见目录，确认没有 Ground Truth 或实现泄漏。

## 回滚

代码变更均限制在 MiniOrder 新增子树、对应文档与构建脚本中。生成的 `artifacts/miniorder/` 可重建；若实现失败，可删除当前任务创建的该生成目录，但不得删除任务开始前已有内容。
