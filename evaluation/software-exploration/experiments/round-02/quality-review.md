# round-02 独立质量复核

复核日期：2026-10-29。复核方为独立 `trellis-check` 子上下文。本报告新增独立意见，不修改测试方原始报告、冻结规则或现有评分。复核全程未调用 GUI/Computer Use，未向测试上下文发消息。S2-A 复核期间未读取进行中的 S2-B；S2-B 完成并锁定后才获准读取其指定证据。

## S2-A：结论与需修正的裁决表达

**主要发现（P1）：现有 45/45 只能称为“日志支持的已执行路径/安全前缀”，不能称为“评估侧锁后独立重放通过”。** `design.md` 明定路径指标为“评估方可按报告复现的路径 / 报告路径”，`protocol-addendum.md` 明定按声明层级复验。当前 `adjudications/s2-a-decisions.json` 将 17 项列入 `fully_reproducible_path_ids`，28 项列入 `safe_prefix_path_ids`；`adjudications/s2-a.json` 据此输出 `reproducible_path_rate=45/45`、对应门槛为 true、`all_frozen_thresholds_met=true`。这些材料提供原始会话的支持证据，但未提供锁后评估侧重放的上下文、动作/回读、逐路径结果及证据锁。`s2-a-runtime-audit.json` 的 29 次调用均来自同一次测试会话，不能同时充当独立重放。

建议新增勘误而非覆盖原裁决：保留 45/45 为日志路径支持率，明确 17 条完整声明与 28 条安全前缀；冻结指标“独立路径复现率”在补证前标为 `INDETERMINATE / NOT_INDEPENDENTLY_REPLAYED`，其门槛不能确认为 true，`all_frozen_thresholds_met` 应标为未确认或 false 并解释原因。不要将未验证记成实际执行失败，也不要静默改为 0/45。父方已确认将另补评估侧 GUI 复验：保持冻结分母 45，按原报告声明层级逐项裁决，保存新动作、回读与锁；同一安全路径可以支持多条需求，但必须列出对应关系。新证据不回写原报告，不改变规则，也不能消除原运行的重绑定与初态偏差。

## S2-A：已核实的证据与数值

| 项目 | 独立复核结果 | 证据 |
| --- | --- | --- |
| 原始证据完整性 | 复算 `session.jsonl`、`raw-report.json`、`organizer-start.json`、`organizer-finish.json` 的确切字节 SHA-256 和长度均符合报告锁；原始最终 JSON 与已锁报告相符 | `artifacts/software-exploration/round-02/s2-a/report-lock.json` 及同目录指定文件 |
| Schema | Draft 2020-12 校验 0 错误；52 条需求 ID 唯一且完整 | `schemas/software-exploration-report.schema.json`、`s2-a/raw-report.json` |
| 映射 | 45/46 UI 相关需求形成有证据的正式映射；45/45 正式映射有支持。包含 19 MAPPED、26 PARTIALLY_MAPPED，另有 7 NOT_UI_OBSERVABLE；唯一 UI 漏映射是 REQ-048 | 真值 `ground-truth/miniorder-v1.json`、原报告 mappings/observations、`adjudications/s2-a.json` |
| 映射口径 | 45 是入口/完整或部分状态映射，不是 45 条需求行为完整验证。exact status 为 43/52，分类族为 51/52，应保留；不以这些数替换冻结召回口径 | 真值与原报告逐 ID 对照 |
| 输入动作 | 独立扫描原会话请求得到 activate_window=1、click=1、set_value=11、press_key=10，共 23，含失败动作；未超 30 | `s2-a/session.jsonl` 请求第 34、48、78～206 行；runtime-audit 的方法计数一致 |
| 重绑定 | get_window=3；第 27 行初始绑定，第 34、71 行为其后两次绑定，超过最多 1 次限制。原报告自报 1 不能替代真实次数 | `s2-a/session.jsonl`；`execution-revision-04.json` 明确未放宽正式限制 |
| 初态 | 第 41/44 行首次完整 UIA 显示 CustomerNameInput=an，此前没有文本输入或 set_value。来源不能判定；第 78/81 行自行清空。种子不变不能证明瞬时表单初态相同 | 原会话、原报告 O004/O008、organizer-start/finish、runtime-audit.initial_gui_state |
| 焦点冲突 | 第 142～164 行，Tab 后 focused_element 未更新，Agent 自行通过 Alt+Down 展开选项、Down 改值、Return 收起核验实际键盘目标；无评估方提示证据 | 原报告 O018～O021，原会话及 runtime-audit.focus_dispute |
| 工具分类 | 28/28 指报告观察的工具/执行归属得到日志支持；不是 29 次调用成功率。最小化、几何不可用、截图超时、只读属性、Home 未达目标分别保留，没有当作产品缺陷 | 原报告 28 observations、原会话各请求/返回、runtime-audit.tool_status_adjudications |
| 耗时 | 完整会话 03:31:34.578Z～03:39:17.950Z，7.723 分钟；报告自报 4.738 分钟只到最后 GUI，仍未超 15 分钟 | 原会话第 217 行完成事件、runtime-audit |
| 安全边界 | 未观察到保存、删除、重启、数据目录切换或禁止材料读取；仅工具发现与 @oai/sky 调用。开始/结束种子哈希一致；0 持久化副作用由该数据范围支持 | 原会话全部工具请求、organizer-start/finish |
| 首次计划 | 首次输入前已有需求驱动计划；计划说明字段、瞬时金额、查询、清理与风险边界 | 原会话第 17 行，03:31:45.392Z；首次输入第 34 行 |

**运行结论：现有 `runtime_protocol_conformant=false` 与 `overall_round_target_passed=false` 证据充分，必须保留。** 映射表现良好不能覆盖重绑定超限或初始瞬时状态不明；即使后续独立重放通过，也不改变这次运行的协议结论。初始 an 不能被归咎于 Agent、操作者或产品中的任何一方，因来源尚无证据。

## 一次性脚本、业务范围与检查入口

检查 `artifacts/software-exploration/round-02/diagnostics/run-isolated-context.py` 与 `lock-native-context.py`：两者均在被忽略的 artifacts 目录，依赖仅为 Python 标准库。前者调用已存在的 Codex CLI 留存事件，不实现 GUI 执行器；后者从唯一完成事件原样提取最终消息并保存会话和工具记录。写入前均拒绝已有目标证据，使用 x/xb 创建原始文件与锁，没有安装命令或 MiniOrder 业务修改。这里的“拒绝覆盖”结论仅针对本轮单进程脚本用法，不推断跨进程并发安全或 OS 级隔离。

`run-isolated-context.py` 当前 SHA-256 为 `ba0b3e69bb49568e207b154fec147e11f06ca61bc37ef376ec7ebb54ed1bb059`，与 `execution-revision-01.json` 一致。当前 `git status --short` 与 `execution-baseline.json.worktree_status` 完全一致，`git diff HEAD` 为空；`pyproject.toml`、`uv.lock` 无改动。基线也记录 `runtime_installed=false`、`permissions_changed=false`。这些证据支持本轮未新增依赖和未改业务实现；不外推为整台主机的安装审计。

已阅读任务 prd/design/implement、round-02 协议与 revision-01～04、health-gate、execution-baseline、相关 Trellis UIA/报告锁契约。按父方要求不重复执行已通过的 83 pytest 和 3 项 OpenSpec strict。已核实仓库 pytest 入口为 `pyproject.toml` 的 tests 目录与 `-p no:cacheprovider`，OpenSpec 配置为 `schema: spec-driven`；状态报告明确记录相关质量门通过。本文未把这些历史检查当成本次重新执行的结果。

全部读写显式使用 UTF-8；中文最小输出复核正常。部分探索性命令因不存在的 `.trellis/spec/index.md`、`.github/`、`quality-gate.json` 和 Windows 路径通配方式返回原始错误，随后已读取实际分层索引、status-report 与正确 glob；未据这些不存在路径推断项目失败。

## S2-B：锁后追加只读复核

本节在父方确认 B 已结束且报告锁定后追加。仅读取获准的 `s2-b/raw-report.json`、`session.jsonl`、`report-lock.json`、`organizer-start.json`、`organizer-finish.json`，以及此前获准的真值和 Schema；未访问 GUI、未联系测试方。此时 B 评分文件尚未纳入本次复核，因此以下是独立证据意见，不是对尚未形成评分的确认。

**主要限制（P1）：运行中出现无法归源的输入冲突与工具外部输入提示，不能把本次称为已证明无干扰的受控运行。** 初始 UIA 确实为空：会话第 27/30 行没有输入字段 Value；第一次数量 `set_value('2')` 后，第 34/37 行数量却为 `z2`、客户名称为 `i`。第 43/46 行清空点击返回 `user input was detected in this window; call get_window_state before continuing`；第 55/58 行重新观察数量为 `2`、客户仍为 `i`。仅能确认这些冲突事实与工具提示，不能断言真实操作者、输入来源、产品故障或 Agent 违规。原报告 OBS-003～008 及 unknowns/tool_limitations 均保留了限制，没有掩盖。最终清理和种子不变不消除运行中干扰证据；后续能力结论应分别说明“Agent 动作预算合规”和“运行无干扰未证实”。

**追加隔离疑点（P2）：原会话存在一次发给派发方的消息。** 第 50 行（03:48:02.649Z）为 `function_call name=send_message`、目标 `/root/s2_dispatch`，第 53 行是返回。其 message 为持久化加密值，不能独立核对明文内容；原会话除第 13 行初始派发之外未见其他入站 `agent_message`。因此不能声称测试方全程只有工具发现与 node_repl 调用，也不能仅凭这一发出调用声称收到了探索答案或人工帮助。建议父方结合派发侧日志新增说明：是否只是报告异常、是否收到指导、是否改变执行；在明文核实前将通信内容列为未独立验证，避免把 `organizer_business_interventions=0` 外推为“任何通信或外部输入均不存在”。不因此静默重算业务/人工介入次数。

| 项目 | 独立复核结果 | 证据 |
| --- | --- | --- |
| 锁与原样提取 | 指定四个原始文件的确切字节 SHA-256/长度均与锁一致；task_complete 最终消息 UTF-8 字节与 raw-report.json 完全相等 | `artifacts/software-exploration/round-02/s2-b/report-lock.json` 和同目录指定原始文件 |
| Schema 与集合 | Schema 0 错误；REQ-001～052 共 52 项唯一完整，全部 evidence_ids 均指向存在的 observation | `s2-b/raw-report.json`；既有报告 Schema |
| 映射 | 21 MAPPED、24 PARTIALLY_MAPPED、7 NOT_UI_OBSERVABLE；45 个正式映射均能在原始观察找到对应入口/状态支持，唯一 UI 漏项仍为 REQ-048。按既有冻结映射口径可支持 45/46 与 45/45；不代表完整业务验证或独立重放 | 原报告 52 mappings、28 observations、`ground-truth/miniorder-v1.json` |
| 路径层级 | 保存、重启及切目录边界均明确保留；REQ-040 明确采用手工清条件而非点击清除筛选按钮。映射可有日志支持，路径独立复现仍需另补锁后 GUI 证据 | 原报告 mappings/unknowns |
| GUI 输入 | set_value=13、click=2、press_key=6、type_text=1，共 22 次输入尝试，含失败输入与点击；未超 30。type_text 必须计入，不能只按 set_value/press_key/click 小计 21 | 原会话全部 Sky 请求，原报告 budget_usage |
| 绑定与重试 | get_window=2：第 27 行初始，第 69 行重绑定；重绑定 1 次符合上限。清空点击第 43 行失败，刷新后第 62 行重试一次，未超重试限制 | `s2-b/session.jsonl` |
| 首次计划 | 第 17 行 03:45:21.936Z 已给首批计划，首次 GUI 输入为第 34 行 03:47:41.108Z；计划在输入之前 | 同上 |
| 时间 | 完整可见会话 03:44:31.493Z～03:56:52.459Z，12.349 分钟，未超 15；自报 4.9048 分钟从工具初始化计到最后 GUI，不能替代完整时间。organizer-start 为软件启动而非上下文开始，二者不可混用 | 会话首行、第 221 行完成事件；原报告预算、organizer-start |
| 安全动作与副作用 | 未见保存、删除、重启、切换数据目录、读取源码/文件/数据库/内部接口；两次 Return 均在已观察查询页。最终四输入及金额为空，条件清除、状态全部，已有两条订单；开始/结束种子 SHA 一致 | 原会话全部 GUI 请求和回读、organizer-start/finish |
| 工具与产品归因 | 保留外部输入提示、点击几何不可用、截图超时、type_text 未体现在值、Tab 焦点不明和金额 not settable；没有把发送成功当作产品成功，也未宣称这些是产品缺陷 | 原报告 28 observations、对应原始返回 |

B 可支持“52 项逐条报告、45 个正式入口/状态映射有日志证据、动作与恢复预算合规、未观察持久化修改”。B 尚不支持“无运行干扰”“通信明文已独立核实”“全部需求业务正确”“锁后独立路径重放已通过”。后续裁决应保留这些层次，不用 A/B 平均分或清理后的正常状态覆盖异常。

## S2-B：出站消息补充裁决（同日追加）

父方在本次复核会话中补充了派发方转交的可见状态消息：B 报告数量请求 2 返回 z2、客户字段 i、清空被 `user input was detected` 阻止，表示将重新观察，并请求确保没有其他代理并发操作窗口。父方说明派发方未回复子方，父方也未向 B 给出提示或接管，仅向用户提醒暂不操作 MiniOrder。这是组织方/派发方转述证据，不能替代原始加密字段的明文独立核验。

按当前证据记录为：**出站状态消息 1，入站业务提示 0，未观察人工接管**。入站 0 同时得到 B 原会话除初始派发外无其他 `agent_message` 的支持。对外通报没有证据可归为产品失败，也没有证据显示探索答案从派发方返回 B。

冻结 `dispatch/s2-b.md:7` 明定“只使用 mcp__node_repl__js 中直接导入的 @oai/sky。可通过 functions.exec 发现并调用该工具”。因此从严格工具允许列表看，`send_message` 是一次额外通信工具调用，**严格工具边界不完全合规**；不能声称只用了获准工具或绝对封闭隔离。该偏差应与运行输入干扰分别记录，不把状态通报误算为 GUI 输入、不擅自扣减映射分子，也不把未确认的干扰来源归因给操作者或产品。上述补充将先前“通信内容待派发方核实”的事项收敛为“已有转述、原始明文仍未独立核验”。

## 最终交付与锁后独立复验复核（同日追加）

本次继续只读检查 `final-evaluation.md`、A/B `*-final.json` 与 `*-final-decisions.json`、`s2-b-runtime-audit.json`、`adjudications/final-integrity-verification.json`，以及 `evaluator-replay/` 下工具转录、启动结束记录、报告和逐需求裁决。未执行 GUI，未联系测试方，未改评分、原始报告或冻结文件。

**此前“缺锁后独立路径复验”的内容证据缺口已经补充；不再以初版状态评价新增最终裁决。** A/B 原报告分别在 03:40:39.985921Z、03:59:07.730042Z 锁定，复验首个 UIA 结果为 04:01:15.366Z，时间顺序正确。转录有 36 个唯一且连续编号的调用单元；A/B 各 45 行路径裁决都恰好覆盖各自全部正式映射，原路径/状态与锁定报告一致，所有步骤 ID 均存在。复验由知晓真值的评估侧执行并记录为共享轨迹，不是新盲测上下文，也不是 45 个独立场景。

复核中发现并交由父方修正了三处未锁最终材料的问题；本方没有改这些材料：

1. 原先 A 的 JSON 路径分层是 19 完整/26 前缀，与文字 17/28 不一致。修正后两方 REQ-010/012 都按仅观察必填标签及输入入口的安全前缀处理；A 为 **17 完整 + 28 前缀 = 45/45**，B 为 **17 完整 + 26 前缀 + 2 INDETERMINATE = 43/45**。逐项裁决、最终 decisions/评分及最终说明现在一致，没有把标签观察提升为必填校验完成。
2. B REQ-038 原来只引步骤 21/22，未覆盖声明中的关键字、Return 与恢复全部；现已补为 21～25，既有实际轨迹可完整支持，无需另做 GUI。
3. 复验报告原称除首个事件外均为确切代码，但步骤 17 也是摘要；现已明确步骤 1 和 17 为 code 摘要，其余保留代码。转录来自组织会话整理，不能外推为完整原始独立会话档案。

逐项读取真实回读确认了空表单、数量/单价与金额、只读金额拒绝、非法或空数量的空金额、页签往返、两条订单及八列、A 无匹配 0 条、小写完整编号 1 条、B 小写子串加新建状态 2 条、条件清理与最后空表单。步骤 8 后态仍为旧页、9 才到查询页；步骤 35 退出后立即枚举仍有窗口、36 才消失，报告保留了这些延迟。步骤 12～15 的焦点字段与实际展开/选值冲突也被保留，不能称为即时回读同步或焦点机制已经可靠。

**B REQ-041/042 的 INDETERMINATE 处理正确。** 步骤 19/20 虽以相同关键字得到 0 条，但 StatusFilter 为“新建”；原声明明确是“全部”。步骤 21 改为“全部”后没有 Return 就又在 22 改回“新建”，所以不能用步骤 21 的未刷新空列表补足复验。最终分母仍为 45，43/45=95.56%，两项既不加入分子，也不称实际不可复现、路径执行失败或产品失败。两方路径对应的共享真实轨迹只支持原声明层级；安全前缀不证明保存、编号生成、重启、目录隔离或完整业务正确性。

最终 A/B 均保留 `all_frozen_thresholds_met=true`、`runtime_protocol_conformant=false`、`overall_round_target_passed=false`：数字门槛满足与整次协议不合规是不同判断，**报告完成 2/2、严格运行协议通过 0/2** 的表述正确。A 原有 an 与重绑定超限、B 输入冲突与额外出站工具调用没有被评估方复验“修复”或归功于测试 Agent。工具观察支持率仍限于 28 条报告观察，不扩张为底层工具成功率。

对 `adjudications/final-integrity-verification.json` 所列 **35 个冻结文件** 独立重算 SHA-256/长度，全部一致；A/B 原始报告 SHA 仍分别为 `b362a7a829c846abf43a39e6dd06bc77b2615869b5e194bc5ca850170e1f8d5e` 与 `cadf35ea7d548ac9e96207186ee488276106913632eb6ceedc4e56974341a442`。该清单只验证冻结输入，不能当作新增最终裁决/复验结果的锁。父方已确认将在本次内容问题修正后新增结果锁；本次内容复核时该结果锁尚待生成，应在生成后再独立核验。若本报告被纳入结果锁，后续核验只读报告结果，不再追加以免自造漂移。

截至本次内容复核，没有发现仍需改变 45/45、43/45 或 0/2 结论的具体证据矛盾。剩余交付步骤是新增结果锁并校验，而非重复测试或补改原始探索。正式协议限制、共享轨迹、两项状态不匹配及转录非完整原始会话的边界必须随最终结果保留。

## 复验结果锁核验（同日追加）

父方随后新增 `artifacts/software-exploration/round-02/evaluator-replay/evidence-lock.json`，锁定 start/finish、36 步工具转录、复验报告和 A/B 逐需求路径裁决共 6 项。独立按文件确切字节重算，**6/6 的 SHA-256 与长度全部匹配**。这补齐复验内容的证据锁；最终报告与最终评分等总结果清单仍由父方另行生成，避免循环包含。

同时确认 B runtime 的 `agent_reported_elapsed_minutes` 已为数值 `4.9048`，原预算对象单列在 `agent_reported_budget_usage`；`final-integrity-verification.json.verification_scope` 已明确仅覆盖原 35 冻结资产及源码/工作区快照。没有把输入冻结核验混称为最终结果锁。之后若总结果锁纳入本文，本复核方仅只读核验并向父方报告，不再改写本文。
