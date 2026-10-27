# MiniOrder MVP 实施计划

## 实施顺序

1. 建立 .NET 8 solution、三个项目、统一编译属性和生成目录忽略规则。
2. 实现 Core 模型、校验、计算、编号、查询和原子 JSON 存储，同时建立 Verification 验证契约。
3. 实现中文 WinForms 两页工作界面，设置稳定控件名、可访问名称、Tab 顺序和错误反馈。
4. 加入编译期 Baseline/VariantA/VariantB 策略，运行三变体契约矩阵并限制每个缺陷的影响范围。
5. 添加固定种子数据、评估方重置工具、中文独立需求、缺陷清单和操作手册。
6. 添加构建、staging 和验证脚本，所有输出写入 `artifacts/miniorder/`，并执行 allowlist 审计。
7. 使用 CUA 完成三个发行包的 Windows GUI 冒烟验证，保存诊断证据并形成就绪报告。

逐项任务与完成复选框以 `openspec/changes/build-miniorder-mvp/tasks.md` 为准；实施时每完成一项立即更新 OpenSpec 状态。

## 验证命令

计划中的最终命令接口如下，具体参数在实现时以脚本帮助信息为准：

```powershell
dotnet restore samples/MiniOrder/MiniOrder.slnx
dotnet build samples/MiniOrder/MiniOrder.slnx --configuration Release --no-restore
dotnet run --project samples/MiniOrder/src/MiniOrder.Verification --configuration Release -- matrix
pwsh -File samples/MiniOrder/scripts/Build-Distributions.ps1
pwsh -File samples/MiniOrder/scripts/Stage-BlackBox.ps1 -Variant baseline
pwsh -File samples/MiniOrder/scripts/Verify-Fixture.ps1
```

GUI 验证不通过终端模拟 UI；使用 Computer Use/CUA 对真实窗口执行，并在每个动作后重新观察状态。

## 风险点与评审门槛

- 金额必须全程使用 `decimal`，不得用 `double`。
- JSON 保存必须先写临时文件再原子替换；异常不得破坏既有数据。
- 缺陷分支只能位于业务策略层，不得污染 UI 文案、程序集身份或数据格式。
- staging 必须采用 allowlist；若出现未识别文件则失败，不得自动放行。
- CUA 动作返回成功不等于业务成功，必须通过动作后 UIA/视觉状态或持久化结果复核。
- 若实现发现需要第三方包、新服务、独立仓库或改变缺陷类型，应返回规划阶段并请求用户确认。

## 完成门槛

- OpenSpec 所有可跟踪任务完成。
- Trellis `trellis-check` 全量质量检查通过。
- AC1～AC10 均有验证证据或明确标为受外部工具限制而未验证；任何关键 False PASS 均阻止完成。
- 用户确认就绪结果后再考虑归档，不在本任务中自行开发测试框架。
