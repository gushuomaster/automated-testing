# MiniOrder 第二轮实验冻结基线

## 不变项

- 源码清单 SHA-256：`5D36F8DBB5886D56950B1E71173CB8E77DFCDEB34E0E66D9E4187922EE2B7DAE`
- 中文需求 SHA-256：`033BEE6C01FE24DDAE53D449B309F44B470A864CDD4583BB4BD7B17B4FDC603F`
- 固定种子 SHA-256：`800B20351B36E56E68AFA23053B87E70391020236FCEE6208F38EC807FD933E7`
- Baseline EXE：`62105E53AA16B042BC86168F4D420D9FC4CCD012B75CF27F7048786C79534B15`
- VariantA EXE：`5873D444BF679579ABB4B013B11EC7AC5DEDCBA713E4DBD2DC35F0DB89393638`
- VariantB EXE：`FD21C817F17DC31C4E6F471E89CD3410B8AABFBA0BF5BB590B5955D3503D388F`

## 环境差异

- 当前 Codex 桌面包路径显示版本 `26.1013.4894.0`；round-01 冻结记录为 `26.1013.40934`。
- 当前 Sky 原生辅助程序位于运行时目录 `cua_node/78fb63cda1a9e2b2`；文件没有可读取的 ProductVersion。
- Windows 仍为 `10.0.19045`，.NET SDK `9.0.312`，OpenSpec `1.14.3`。

因此，程序与业务输入保持不变，但工具宿主版本发生变化。round-02 结果不能只归因于新增入口和证据规则；工具版本是两轮比较的混杂因素。

## 工作区

仓库位于 `D:\project\agent\automated-testing`，分支 `main`，无 Git HEAD。round-01 及此前 MiniOrder 文件均为未提交工作，全部保留。round-02 以哈希冻结，不把工作区称为已提交版本。

## 可比性

程序、需求、种子、预算和评分不变；测试流程新增正确入口、健康检查和争议核验规则，同时 Codex 桌面包版本变化。比较结果时应把流程和工具版本变化共同视为干预，不能归因于产品变化，也不能据此分离各自影响。
