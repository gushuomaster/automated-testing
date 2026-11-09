# 独立质量复核

2026-10-29。结论：本轮最小资格诊断的证据与结论相符，未发现需要继续扩大实现的阻断问题。UFO 资格仍为 **NOT_ADMITTED**，正式比较为 **NOT_STARTED**；离线防线、一次模型兼容和独立 Sky 健康检查均不能替代完整框架准入。当前停止于已授权的最小验证范围。

## 范围与方法

按 `trellis-check` 独立读取 AGENTS、任务 PRD/design/implement、check/implement.jsonl、相关 backend 规范与上一轮比较协议。审查本轮脚本、33 项测试、新执行契约及 index 行、三个交付报告、主方 integrity、全部 diagnostics、候选客户端补丁与原生相关调用路径。仅本文件由本复核者写入；没有修改旧文件、执行模型探针、读取全局凭据、调用 API、操作 GUI 或安装依赖。

独立重跑使用项目现有 `.venv/Scripts/python.exe -B`：新边界测试 **33/33**，全量 pytest **116/116**；另以 `compile()` 编译两个新文件而不执行其业务代码。已读取主方 `validation.json` 的 compileall、`uv lock --check` 成功记录，以及 OpenSpec Python subprocess 找不到 shim 的原始失败和当前 PowerShell 后续 **3/3** 成功记录；未隐去首次失败，也未为检查重跑模型请求。

## 完整性核对

独立按实际文件字节重新计算 SHA-256：

| 核对对象 | 结果 |
| --- | --- |
| 上轮调查 evidence-lock | 55/55 一致；锁自身 SHA-256 为 `84d6e64df9f3bc751d8a486d2a0d38018b1120b64866a0605aa4b20c942b1a75` |
| 旧 S2 freeze | 35/35 一致；freeze.json 与 freeze-lock 一致 |
| 旧 S2 results-lock-revision-01 | 21/21 一致 |
| 固定 UFO 原工作树 | Git 状态干净，HEAD 为 `eae3c0a8d168c47cb10df0652e293e092eda1078` |
| 候选 252 文件 | 与原工作树已有文件逐字节比较，仅 `ufo/llm/claude.py` 改动；25 个新展开 aip 文件与固定提交规范化换行后全部一致，无额外内容差异 |
| 候选 claude.py | 补丁前后 SHA-256 均与 environment-and-patch.json 一致 |
| 主项目依赖 | pyproject.toml、uv.lock 与 HEAD 原始字节一致 |
| 本次健康资产 | MiniOrder.exe 与种子 orders.json 均匹配事前协议哈希 |

Windows 工作树及展开的 aip 使用 CRLF，上游 Git blob 使用 LF，因此候选所有文件不能宣称与 Git blob 原始字节相同；“唯一修改”准确指已有工作树文件中的实质源码修改。旧锁仍按原始字节核验，不做换行归一化。

## 覆盖与限制复核

1. **真实模型层级明确。** probe 源码确实调用候选 UFO `ClaudeService.chat_completion`，继而使用原生消息转换；仅构造器补配置 endpoint、SDK `max_retries=0` 和 60 秒超时。`MAX_RETRY=1`、`n=1`、512 token 上限与结果中一次 HTTP 200 相符。通用中文输入只要求 `{"状态":"可用"}`，返回合法 JSON；没有 Host/App 完整响应 Schema、业务规划、长期可靠性或完整 Agent 证据。price 映射缺失导致 cost=0，不是免费证明。
2. **原生执行仍阻塞。** 导入记录保留 dispatcher/basic/aip.Command 的 fastmcp 缺失和 inspector 经 Excel 注册引入 pandas 的失败。源码确认 Host/App 多条直接截图路径绕过 dispatcher；关闭 VISUAL_MODE 或拒绝 capture 命令均不足以证明全链路纯 UIA。没有真实 native dispatcher 注入、工具注册清单、实时归属回调、原生窗口健康或完整循环通过记录。dry-run 不等于安装完成。
3. **wrapper 是局部离线防线。** 33 项测试使用明确 fake callback；覆盖越权拒绝、参数/复合输入拒绝、窗口与控件归属、整批预算预检、失败占账、同一完整参数指纹原始一次加两次失败重试、批内失败停止、并发输入预算和逐条 deadline。`texts` 已因原生接收器隐含 set_focus 被拒绝，未冒称零成本读取。整批预检拒绝才保证整批下游零调用；逐条复查拒绝只保证该条未调用，已经执行的前缀仍留账。复核指出此措辞后，主方已修正规范契约及错误矩阵，现与实现一致。
4. **局部预算不能推导全面保证。** 计数仅覆盖显式单击尝试，不能证明所有原生焦点/键鼠子事件已计量；失败指纹按工具、类型、完整参数识别，不是业务语义等价判定。同步 Windows 工作可能在取消后继续，原生吞错也可能上报 success。固定窗口归属不等于非破坏性目标，同窗口保存按钮仍能持久化；真实接入必须另限定允许目标并独立回读。这些限制已在规范与报告中明确，未被计为通过。
5. **Sky 证据独立成立。** agent-events.json 的 GO、最后退出确认、动作记录可复算为 150.514 秒、4/6 输入（activate、两次 Ctrl+Tab、Alt+F4），工具错误 0，截图数组为空；即时/延后回读差异被保留，没有据此盲重试。种子哈希不变。它仅支持本次 Sky 最小观察→动作→回读，不证明 UFO 原生 UIA、自主探索、OS 独占或旧实验问题已消除。
6. **环境与下载表述受限。** 43 包解析冻结及约 65.4MiB 安装后文件不等于完整上游环境；没有装整套 RAG/FAISS/torch。未采集网络总字节，报告正确地未把 150MiB 目标称作已实施网络硬上限。

## 文本与凭据检查

新增 authored 文本严格 UTF-8 读取与 17 份 JSON 解析通过，未见替代字符；普通高风险 token 形态扫描未在新增报告、诊断、脚本或规范发现疑似密钥。候选中的 API_KEY 命中经复核属于上游空值、`ollama`/`your_api_key` 等占位符、类型定义或变量引用；不据这些命中误报泄露。没有读取真实全局 key 作比对，因此结论限定为本次静态内容审查，而非所有可能 secret 格式的穷尽证明。probe 源码保留凭据读取路径和变量名，没有记录凭据值；本次没有执行它。

检查使用 PowerShell，显式设置 Console/OutputEncoding 为 UTF-8。首次 Python 输出中文受子进程 stdout 编码影响，随即停止文本修改、确认源文件与 shell 编码，并设置 `PYTHONUTF8=1` 后以“中文 UTF-8 复核通过”验证正常；没有替换乱码掩盖根因。一次只读误读 `.jsonl` 路径报不存在，随后按实际 `agent-events.json` 读取，未将路径错误解释为缺失运行证据。

## 收尾状态

主方 integrity-verification.json 已生成，其旧锁、候选、依赖与健康资产结论与本复核一致。**本复核完成时新的 evidence-lock.json 尚未生成，故不宣称新锁已验证通过。** 主方应在本文件写入后按最终字节生成并复算本轮证据锁；该锁只保护资格诊断，不是正式比较冻结。

不建议在当前轮继续补包、扩大纯 UIA 策略修改、运行模型或用 mock/Sky 补成 UFO 通过。后续若继续完整 UFO，需另有明确范围与授权，先完成原生工具边界和健康门；本轮没有新正式成绩或框架优劣排名。
