# KeePassXC M1 基准（自主探索）

被测版本：KeePassXC 2.7.6 便携版（`artifacts/feasibility-01/downloads/kpxc-2.7.6/app/KeePassXC-2.7.6-Win64`）。

| 文件 | 用途 | Agent 是否可见 |
|---|---|---|
| `seed.kdbx` | 每个章程开始前复制到运行目录的种子库，主密码 `Test@2026` | 通过 GUI 可见；密码写在任务提示里 |
| `manual/*.adoc` | 用户手册节选（界面、数据库操作、快捷键、密码生成器），规划和判断期望行为的唯一文档依据 | 可见 |
| `truth.json` | 候选历史缺陷与复现确认状态，用于度量召回 | 不可见 |
| `make_seed.py` | 种子库生成脚本 | 不可见 |

## 种子库生成

`keepassxc-cli` 2.7.6 的 `add` 命令不能设置 TOTP，所以脚本先生成 KeePass XML，再用 `keepassxc-cli import` 导入。TOTP 存成条目的 `otp` 字段，值为 otpauth URI，与 KeePassXC 自带 TOTP 设置对话框的存储格式一致。生成后脚本做两项校验：`export` 后用 `parse_export` 核对群组和条目，`show --totp` 确认能算出 6 位验证码。UUID 和时间戳固定，重跑的内容相同（kdbx 文件本身因加密随机数会不同）。

```
.venv\Scripts\python.exe benchmarks/keepassxc-m1/make_seed.py
```

内容：根群组“密码”下有 2 个条目，另有 网银（2）、邮箱（3）、工作（3）三个子群组；`工作/GitHub` 带 TOTP。条目数据是普通账号，不包含任何指向候选缺陷的文字。

## 真值维护

`truth.json` 里四条候选缺陷初始为 `pending`。组织方在 2.7.6 上逐条复现后，把结论和步骤写进 `.trellis/tasks/11-10-m1-autonomous-exploration/research/repro-<id>.md`，再把 `repro_status` 改成 `confirmed` 或 `excluded`，`repro_basis` 填文档路径。只有 `confirmed` 计入召回分母。
