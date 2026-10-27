# MiniOrder 首轮实验冻结基线

## 工作区

- 仓库：`D:\project\agent\automated-testing`
- 分支：`main`
- Git 状态：尚无首个提交，`HEAD` 不存在；所有项目文件均处于未跟踪状态。
- 冻结方式：逐文件 SHA-256 清单，而不是 Git commit。
- 源码清单：`artifacts/miniorder/experiments/round-01/baseline/source-manifest.json`
- 清单 SHA-256：`5D36F8DBB5886D56950B1E71173CB8E77DFCDEB34E0E66D9E4187922EE2B7DAE`
- 中文需求 SHA-256：`033BEE6C01FE24DDAE53D449B309F44B470A864CDD4583BB4BD7B17B4FDC603F`

任务开始前存在的未提交内容全部保留；本轮不提交、不覆盖或移动这些文件。

## 私有发行基线

| 身份 | 角色 | SHA-256 |
|---|---|---|
| Baseline | 正确对照 | `62105E53AA16B042BC86168F4D420D9FC4CCD012B75CF27F7048786C79534B15` |
| VariantA | 数量下边界缺陷 | `5873D444BF679579ABB4B013B11EC7AC5DEDCBA713E4DBD2DC35F0DB89393638` |
| VariantB | 金额计算缺陷 | `FD21C817F17DC31C4E6F471E89CD3410B8AABFBA0BF5BB590B5955D3503D388F` |

固定种子 SHA-256：`800B20351B36E56E68AFA23053B87E70391020236FCEE6208F38EC807FD933E7`。

代码和契约矩阵复核结果与私有缺陷清单一致：Baseline 无已知差异；VariantA 仅错误接受数量 0；VariantB 仅错误使用加法计算金额。

## 环境与工具

- Windows 10 Pro 22H2 x64，build `19045.6456`
- PowerShell `7.6.5`
- .NET SDK `9.0.312`
- OpenSpec `1.14.3`
- Trellis `0.6.17`
- Codex App `26.1013.40934`，build `20770`，prod
- Computer Use 插件 `26.1013.40934`
- 测试线程模型：不覆盖，使用 Codex App 配置的默认模型；线程创建 API 未提供可冻结的精确模型名，因此这是复现限制。

## 需求充分性

中文需求独立规定了输入边界、金额公式、保存约束、编号、状态、查询、完整显示和持久化，足以推导测试和判断结果；没有版本身份、植入缺陷清单、具体缺陷触发答案或实现技术。

## 工具适用范围

已核实 UIA 可读取输入、状态和 DataGridView 八列值，可通过标准键盘命令完成保存和查询。截图通道仍超时，元素点击几何可能不可用。本轮因此只评价 UIA 路径。
