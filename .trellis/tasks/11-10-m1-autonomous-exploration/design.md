# M1 技术设计

## 边界

- 复用 M0：`Agent` 循环、`Budget`、`DesktopClient`、`KeePassXCEnv`、`ClaudeModel`、`checks`/`DbSnapshot`。M0 的行为和测试不变。
- 新代码都在 `src/testing_platform/autotest/` 下。虚拟机隔离属于 M1b，不在本任务；执行入口只依赖 `Desktop` 协议（`call(op, timeout, **args)`），以后可换成 `RemoteDesktopClient`。
- Agent 只能通过 GUI 接触被测软件，看不到真值、种子库路径、其他章程的原始日志。

## 模块

| 模块 | 职责 |
|---|---|
| `agent.py`（改） | `Agent` 新增可选参数 `system_prompt`、`extra_tools`、`handlers`；不传时与 M0 完全一致 |
| `defects.py`（新） | `parse_report_defect` 校验、`DefectReport`、`NoteBook`、报告去重合并 |
| `explore.py`（新） | 规划、逐章程执行、汇总、`--score` 度量、命令行入口 |
| `benchmarks/keepassxc-m1/`（新） | `seed.kdbx`、`manual/`（四份 adoc 节选的副本）、`truth.json`（组织方维护，不进 Agent 输入） |

## 框架内工具（note / report_defect）

- 由 `handlers[name](args, ctx) -> (msg, is_error)` 处理，不走桌面服务，不占动作预算，不触发新观察。
- `ctx` 带最近一次观察的编号、截图路径和当前章程 id。`Agent` 在每次 `_observation_content` 后更新 `last_obs`。
- `report_defect` 的证据只取 `last_obs`。与 `finish` 同理：同一轮里排在动作之后的 `report_defect` 不接受（证据会对不上），提示先看动作后的观察再报告。
- `report_defect` 字段：`title`、`steps`（非空字符串列表）、`expected`、`expected_source`（`manual:<章节>` 或 `general`）、`actual`、`severity`（`low|medium|high`）。缺字段、空值、非法枚举一律参数错误，不入库。
- 每章程最多 5 条报告、笔记单条长度封顶，超出返回错误而不是静默丢弃。
- 报告和笔记各写一行到 `steps.jsonl`（`kind=defect` / `kind=note`），与动作日志同一时间线。

## 流程

1. 规划（无 GUI）：一次模型调用，强制使用 `submit_charters` 工具，输入是四份手册节选全文（约 38 KB）。输出 4 到 6 个章程 `{id, title, area, focus, manual_refs, max_actions}`。开启 thinking 时 API 不能强制工具调用，实测 5 次规划里有 2 次失败（一次章程数不对，一次只回文字）。因此失败时把原因反馈给模型重试，最多 3 次：校验错误以 `tool_result` 返回，没调用工具则提醒调用。失败记录写入 `plan.json` 的 `failed_attempts`，全部失败时写 `plan-failed.json` 并报错。不用默认章程兜底。
2. 章程执行：每个章程重置环境（还原种子库和配置）、启动软件、`set_target`、新建 `Agent`（新上下文）、运行、关闭。任务提示 = 测试目标一句话 + 章程 + 前序章程的笔记（只含 `note` 内容，不含前序报告）。预算：每章程 `Budget` 加总预算（总动作、总模型调用、总墙钟）；总预算用尽则剩余章程标记 `skipped_budget`。
3. 汇总：一次无工具模型调用，对所有报告做重复分组；合并时保留首条，并列出被合并报告的证据。调用失败则保留全部并标记 `undeduped`。同时输出覆盖的章程和手册章节。

## 系统提示

探索用提示与 M0 的执行员提示分开。要点：只依据手册和通用软件准则判断缺陷；报告前先重现一次；不得猜测；不得关闭软件；不提示任何具体缺陷。提示文本里不出现真值缺陷的症状词，由测试断言。

## 真值与度量

- `truth.json`：每条候选缺陷 `{id, symptom, fixed_in, repro_status, repro_basis}`，`repro_status` 只有 `confirmed|excluded|pending`，只有 `confirmed` 计入召回分母。
- `judgement.json`（人工填写）：每条去重后报告 `{report_id, label, truth_id, basis}`，`label` 取 `known|new|not_defect|undetermined`。框架不自动判定。
- `--score` 读 `reports.json`、`truth.json`、`judgement.json`，输出召回、精确率、章程覆盖、动作、耗时、token、费用；缺少判定的报告列为 `unjudged`，不计入精确率分子或分母。

## 产物目录

`artifacts/m1-runs/<时间戳>/`：`plan.json`、`charter-N/{steps.jsonl,shots/,result.json,data/}`、`notes.json`、`reports.json`、`report.md`、`summary.json`。

## 测试（离线，不碰 GUI 和模型 API）

- 工具校验：缺字段、非法严重度、超上限、同轮动作之后的 `report_defect`。
- `Agent` 带 handlers 时：笔记和报告不占动作预算、证据取最近观察；不带时与 M0 行为一致（M0 测试原样通过）。
- 规划输出校验、预算耗尽后跳过章程、去重失败降级、`--score` 的召回和精确率计算、提示文本不含真值症状词。

## 复用与自研结论（2026-11-13）

- 已查：S2 复用调研（Windows-MCP、Agent-S、TESTAR，UFO、UI-TARS、Midscene 的初步判断）；联网检索了 GUITester、GUITestScape、UI-KOBE、LLM-Explorer、Temac、KG-RAG。后者只看了搜索摘要，没有读论文和代码，不当作已验证结论。
- 结论：没有找到面向桌面软件的成熟开源探索式测试工具。桌面执行层和探索循环继续自研，S2 里复用 Windows-MCP UIA 子包的决定不变。
- 借鉴项，不进首轮基线：
  1. 报告验证步骤（GUITester 思路）：单独的模型调用审查每条报告的截图证据和复现步骤，区分软件缺陷与操作失误，目的是提高精确率。
  2. 知识图谱对照实验：探索图（界面状态为节点、动作为边）和手册图（功能点与期望行为），先跑无图谱基线，再对比增益。桌面软件的状态抽象是否有效，目前没有证据。

## 跨领域借鉴：探索能力抽象与自进化（2026-11-13）

用户提醒：自动探索的特性不只属于桌面软件，可以从移动端和 Web 端的 GUI 测试、自进化 agent 借鉴。已联网检索，下面除 AdaptiTest 读过摘要外，其余只看了搜索摘要。

- 探索能力与平台无关的部分：章程规划、期望来源（手册或通用准则）、证据绑定、预算、去重、报告验证、记忆。只有观察和动作层与平台相关，本设计已通过 `Desktop` 协议隔开，因此探索核心（`explore.py`、`defects.py`）不应依赖 Windows 细节。
- 移动端已有较多同类研究：GPTDroid（功能感知记忆）、DroidAgent（以界面状态为键存取任务知识，记忆限于单次运行）、GraphDroid（保留已访问状态的截图和迁移并聚类，指出摘要式历史会丢失未测功能的线索）、AutoDroid/AppAgent（预先探索建 UI 迁移图或控件知识库，用于完成任务而非测试）。
- 自进化：Hermes Agent（Nous Research，开源）的学习循环是“解决、沉淀为技能、检索、改进”，有容量受限的记忆文件和按需加载的技能。GUI 方向有 EvoSkill-GUI、SEAgent、UI-Voyager、Mobile-Agent-E 等，主要衡量任务成功率，不衡量缺陷发现。
- AdaptiTest（arXiv 2611.05873，读过摘要）：跨会话经验带适用范围、来源轨迹，以及确认、复验、撤回的生命周期；只有 Reflector 角色写入持久记忆；召回的经验只作建议，与当前观察冲突时撤回。作者自己说明证据有限：跨会话实验因混杂因素被排除，结论不足以证明普遍有效。
- 结论：首轮基线不加跨运行记忆。当前“章程间只传笔记、不传报告”是运行内记忆的最小形式。跨运行经验库作为第三个后续实验，放在报告验证和知识图谱之后，规则如下：
  1. 经验库只存操作知识（如何到达某个界面、如何处理某个对话框），不存缺陷结论，否则后一次运行的召回不独立。
  2. 每条经验记录来源运行和观察编号，并标注适用的软件版本；当前观察与经验冲突时，以观察为准并标记该条待复验。
  3. 写入由运行结束后的单独整理步骤完成，探索中的 agent 不直接写持久库。
  4. 对照方式：同一章程集合，分别用空库和上一次运行沉淀的库各跑一次，比较召回、精确率和无效动作占比。

## 虚拟机执行（2026-11-13）

- 入口：`python -m testing_platform.autotest.explore --remote 192.168.53.129:8765`。会话工厂 `remote_session` 每个章程新建连接，依次 `kpxc_reset` → `kpxc_launch` → `set_target`，结束时总是 `kpxc_stop`，结果写到 `charter-N/stop.json`。不带 `--remote` 又没有 `--local` 时拒绝运行。
- 来宾端 `kpxc_*` 每个操作在独立子进程里执行（`keepassxc_guest.py`），状态存在 `C:\autotest\run\state.json`。原因：run-02-vm 中远程服务主进程在 `_ctypes.pyd` 访问冲突（0xc0000005）崩溃，C3–C6 全部连不上。推断是 `stop()` 里的 UI Automation（COM/ctypes）在每连接各自的线程上执行所致，这一点没有用旧代码复现确认。修复后连续 5 轮干净循环、5 轮带未保存改动的循环服务都保持在线。
- 子进程输出必须是纯 ASCII JSON：来宾管道按 GBK 编码，非 ASCII 会被替换成乱码。首版修复就出现过这个问题，导出里的中文条目名撞键，10 个条目被数成 9 个。已由单测覆盖中文往返。
- 本机 run-01 作废（误在本机桌面运行）。run-02-vm 只有 C1、C2 有效，整轮重跑为 run-03-vm。

## 待验证

- 已验证（2026-11-13）：`keepassxc-cli` 2.7.6 的 `add` 没有 TOTP 选项；改用 `benchmarks/keepassxc-m1/make_seed.py` 生成 KeePass XML（TOTP 存为 `otp` 字段的 otpauth URI），再 `keepassxc-cli import`，并用 `show --totp` 和 `export` 校验。方法写在该目录的 README.md。
- 四条候选缺陷在 2.7.6 上的复现确认是人工前置工作，结果写入 `research/repro-*.md`，再更新 `truth.json`。
