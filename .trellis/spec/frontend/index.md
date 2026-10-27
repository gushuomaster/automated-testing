# 前端开发规范

> 本项目桌面界面开发的可执行约定。

---

## 概览

本目录记录前端和 Windows 桌面界面的项目级约定。实现前应先阅读与改动相关的规范文件。

---

## 规范索引

| 规范 | 说明 | 状态 |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [组件与桌面控件规范](./component-guidelines.md) | WinForms 控件、可访问性和键盘操作约定 | 已启用 |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, data fetching patterns | To fill |
| [State Management](./state-management.md) | Local state, global state, server state | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Type Safety](./type-safety.md) | Type patterns, validation | To fill |

---

## 开发前检查

修改 Windows 桌面界面前必须：

1. 阅读 [组件与桌面控件规范](./component-guidelines.md)。
2. 确认新增控件具有稳定的 `Name`、中文 `AccessibleName` 和确定性的 Tab 顺序。
3. 为关键命令提供标准键盘路径，并验证 UIA 操作后的可观察状态。
4. 将截图或 UIA 执行器限制与产品行为失败分开记录。

---

**语言**：项目规范默认使用中文；代码标识符、API 名和工具错误信息可保留英文。
