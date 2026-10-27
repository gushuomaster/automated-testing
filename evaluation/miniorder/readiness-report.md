# MiniOrder MVP 就绪报告

## 当前结论

截至 2026-10-21，MiniOrder MVP 已达到第一阶段黑盒自主测试实验的启动条件。产品实现、三变体构建、核心契约、数据重置、黑盒隔离和 Windows CUA 冒烟均已完成。

当前状态为“实验就绪（UIA 路径）”。Computer Use 的 Windows.Graphics.Capture 截图通道在本机持续超时，因此不能把本轮结果描述为“截图路径已通过”；该限制属于执行器能力，不影响 UIA 对完整订单行、保存状态、重启持久化和受控缺陷行为的确认。

## 构建与 Ground Truth

| 私有身份 | `MiniOrder.exe` SHA-256 | 契约矩阵 |
|---|---|---|
| `Baseline` | `62105E53AA16B042BC86168F4D420D9FC4CCD012B75CF27F7048786C79534B15` | 无差异 |
| `VariantA` | `5873D444BF679579ABB4B013B11EC7AC5DEDCBA713E4DBD2DC35F0DB89393638` | 仅数量 0 未拒绝 |
| `VariantB` | `FD21C817F17DC31C4E6F471E89CD3410B8AABFBA0BF5BB590B5955D3503D388F` | 仅金额乘法契约失败 |

三个发行包的产品名、文件描述、版本、窗口标题和 UIA 树一致。固定种子重置后的 SHA-256 为 `800B20351B36E56E68AFA23053B87E70391020236FCEE6208F38EC807FD933E7`。

## 已通过检查

- Release 构建在 warnings-as-errors 下为 0 警告、0 错误。
- 22 项核心边界契约通过，JSON 往返、损坏数据、schema 和目录隔离检查通过。
- 连续重置产生相同哈希，实验新增订单被移除。
- 中性黑盒目录 allowlist 通过，只包含 `MiniOrder.exe` 和 `MiniOrder-Requirements.md`。
- staged EXE 可启动并正常关闭；主窗口标题为“MiniOrder - 订单管理”。
- UIA 能识别两个页签及关键字段、按钮、状态和查询控件。
- UIA 工作流确认有效订单只保存一次、无效订单不新增、查询命中 1 条，使用同一数据目录重启后仍命中 1 条。
- WinForms 默认按钮合约确认新建订单页按 Enter 触发保存、查询订单页按 Enter 触发查询，切回新建页后恢复保存入口。
- CUA 基线流程确认 `3 × 12.50` 显示 `37.50`，按 Enter 保存后出现订单号和“新建”状态；查询表格公开并显示订单编号、客户、商品、数量、单价、金额、状态和创建时间。
- 使用同一数据目录重启后，CUA 读回的八个订单字段与保存前一致。
- CUA 确认 `VariantA` 错误地接受并保存数量 0，`VariantB` 对 `3 × 12.50` 错误显示 `15.50`。
- 重置命令产生固定哈希，并由 CUA 在重启后的查询页确认只剩两条固定种子订单，实验新增订单已清除。

## 黑盒边界

AI 可见目录为 `artifacts/miniorder/blackbox-run/`，只允许：

- `MiniOrder.exe`
- `MiniOrder-Requirements.md`

源码、PDB、构建脚本、验证程序、种子、缺陷清单、变体名称、预制操作和评估答案均不在该目录。评估方应在授权 GUI 工具之前完成数据重置并启动软件，不向测试 AI 授予仓库或评估目录的文件系统访问。

## 已知限制

- Computer Use 的截图调用两次返回 `window capture timed out: timed out waiting on channel`。本轮没有伪造或用文件内容替代截图证据。
- Computer Use 无法通过元素索引点击当前 WinForms 按钮，错误为 `coordinate input geometry is unavailable`。应用已提供标准 Enter 默认按钮路径，CUA 可在不依赖坐标的情况下完成保存和查询。
- UIA 在页面切换后的第一次快照偶尔只返回部分树；重新观察即可获得稳定的完整树和 DataGridView 单元格值。

这些限制已与产品断言分开记录。若后续实验要求纯视觉识别而不允许 UIA，应先修复或替换截图执行器；当前样本适合验证“需求文档 + 可运行软件 + UIA/键盘操作”的第一阶段自主黑盒测试。

本轮 CUA 明细保存在 `artifacts/miniorder/diagnostics/cua-final-evidence.md`。
