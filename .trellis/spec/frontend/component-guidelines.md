# 组件与桌面控件规范

## 适用范围

当前项目的前端样本是 `samples/MiniOrder` 下的 .NET 8 WinForms 应用。本规范适用于新增或修改窗口、页签、输入框、命令按钮、状态消息和数据表格。

## 控件身份

- 用户可操作或需要断言的控件必须设置稳定、中性的 `Name` 和中文 `AccessibleName`。
- 不得在普通窗口标题、控件文本、文件名或数据格式中暴露 `Baseline`、`VariantA`、`VariantB` 等私有版本身份。
- 使用 WinForms 标准控件；MVP 不使用自绘按钮、自定义 Canvas 或仅图标命令。

示例：

```csharp
private static Button CreateButton(string name, string text, int tabIndex) => new()
{
    Name = name,
    AccessibleName = text,
    Text = text,
    AutoSize = true,
    TabIndex = tabIndex
};
```

## 键盘与 UIA 契约

每个主要工作页必须有不依赖屏幕坐标的标准键盘命令路径。对于页签式 WinForms 窗口，根据当前页设置 `Form.AcceptButton`，使 Enter 触发该页的主命令：

```csharp
private void UpdateAcceptButton(TabControl tabs) =>
    AcceptButton = tabs.SelectedIndex == 0 ? _saveButton : _queryButton;
```

原因：当前 Computer Use 运行时可以读取 UIA 树和设置输入值，但个别 WinForms 按钮可能不提供可点击几何，返回 `coordinate input geometry is unavailable`。标准默认按钮既改善键盘可访问性，也为黑盒执行器提供稳定路径。

## 可观察结果

- 执行动作后必须通过用户可见状态或 UIA 回读确认结果，不能把“输入已发送”当成业务成功。
- 保存命令应暴露成功/失败状态；查询命令应暴露结果数量和完整表格行值。
- DataGridView 行值应使用只读标准单元格，确保 UIA 可以读取订单编号、客户、商品、数量、单价、金额、状态和创建时间。

## 必需测试

- STA WinForms 合约：确认每个页签的 `AcceptButton` 指向正确按钮，调用 Enter 后断言保存或查询结果。
- UIA 冒烟：设置输入值、执行命令、回读状态，并验证同一数据目录重启后的显示值。
- 执行器限制：截图超时、树不完整或点击失败必须单独记录，不得据此把产品结果标为通过或失败。

## 常见错误

- 只验证按钮存在，没有验证键盘可执行路径。
- 页面切换后继续复用旧 UIA 索引；任何状态变化后都必须重新观察。
- 用持久化文件内容替代 GUI 查询结果。文件可用于内部交叉验证，但黑盒结论必须来自获准的 GUI 观察路径。
