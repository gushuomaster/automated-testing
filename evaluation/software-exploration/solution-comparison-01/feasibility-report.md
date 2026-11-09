# UFO²最小接入调查

2026-10-29。结论：UFO值得作为现成候选继续评估；当前默认配置未满足本项目纯UIA黑盒探索边界，尚不能直接开始正式比较。没有安装上游依赖、执行UFO入口、调用模型API或修改MiniOrder。

## 固定依据

上游为<https://github.com/microsoft/UFO>，提交`eae3c0a8d168c47cb10df0652e293e092eda1078`。只读浅稀疏副本在`artifacts/software-exploration/solution-comparison-01/research/UFO`；下列路径/行号相对此副本。18个关键文件及源码摘录哈希见`research/source-manifest.json`。MIT许可证见`LICENSE:3`。

| 确认的代码事实 | 对本项目的含义 |
| --- | --- |
| `ufo/README.md:76` HostAgent负责目标与状态机，`:77` AppAgent采用ReAct循环 | 已有探索循环与应用控制组织，不必从零写相同结构；不等于已经满足需求映射任务 |
| `config/ufo/system.yaml:11` UIA backend，`:107` MCP；`ufo/module/dispatcher.py:67` LocalCommandDispatcher | 存在单机路径，无需先接入跨设备Galaxy或另建服务；本机未运行验证 |
| `config/ufo/mcp.yaml:28`、`:45`默认暴露CommandLineExecutor，后续应用配置还有COM | 仅写“不要用命令”不足以限制能力，需配置移除并核对实际工具列表，仅保留目标窗口GUI/UIA |
| `app_agent_processor.py:91`组合ScreenshotCapture与ControlInfo；`strategies/app_agent_processing_strategy.py:129`采集窗口图；`host_agent_processing_strategy.py:99`采集桌面图 | 默认流程会采集截图，存在超出目标窗口的观察范围 |
| `ufo/prompter/agent_prompter.py:128`、`:311`按is_visual决定是否把图发给模型 | VISUAL_MODE=False限制模型附图，不能据此宣称禁止了截图采集；纯UIA采集仍需适配及核验 |
| `system.yaml:15` MAX_STEP；`ufo/agents/processors/core/processor_framework.py:224`、`:229`递增处理步数 | 轮次不等于GUI输入数，MAX_STEP=30不能冒充30次动作硬上限 |
| `ufo/automator/ui_control/controller.py:182`的set_edit_text含Ctrl+A、Delete、输入及恢复路径 | 复合命令/失败重试必须可审计，不能漏计实际调用或用一轮隐藏多动作 |
| `ufo/module/dispatcher.py:94`命令默认timeout=6000，`:108`附近使用asyncio.wait_for；`system.yaml:5`模型重试默认20 | 默认超时/重试不能直接等同15分钟、失败最多重试2次的实验约束 |
| `ufo/module/basic.py:601`、`:604`、`:607`已有response/request/evaluation日志 | 可复用证据出口，但并未证明会产出本项目Schema、原始锁或需求映射 |
| `config/ufo/rag.yaml:4`、`:9`、`:14`、`:19`默认RAG关闭 | 有利于避免旧知识；仍需新日志/记忆目录和实际输入审计 |
| `ufo/README.md:80`、`:479`将隔离桌面PiP标为coming soon/开发中 | 不能靠此功能宣称已解决键鼠干扰或实现OS隔离 |

上表processor与strategy缩写路径均在`ufo/agents/processors/`下。证据是静态代码阅读，不是UFO实机能力通过。

## 实际环境

Windows 10 build19045符合上游文档Windows>=10要求；项目Python为3.14.3。上游`requirements.txt`固定pywinauto0.6.8、openai1.66.2、Pillow11.3.0、pydantic2.11.7、pandas1.4.3等，含RAG/服务依赖，不能直接覆盖项目环境。当前环境缺pywinauto、pywin32、comtypes、openai、psutil，见`environment.json`。

本机已有uv管理的Python3.10.20，可作为后续隔离环境候选；PyPI元数据中pandas1.4.3 Windows现成wheel最高cp310。它只解释为何优先试3.10，不是完整依赖解析或安装成功证明。`py -3.10`/`py -3.11`在本机不能匹配这些runtime，但`uv python list --only-installed`及显式绝对路径运行均成功；不要将launcher匹配失败说成未安装。3.10/3.11实测及wheel名称见`research/runtime-probe.json`。旧Hermes Python3.11环境已有部分包，但版本不同，不能当作UFO现成环境，也未修改它。

模型方面：当前进程没有常见OPENAI/AZURE环境配置，新UFO副本没有agents.yaml；但本机Hermes存在MiniMax-M2.7配置及非空凭据。因此“本机没有模型凭据”不成立。只核对存在性，未打印/复制密钥、未调用模型；MiniMax与UFO调用方式、结构化输出、成本和错误处理均未验证。UFO支持OpenAI等服务的源码入口见`ufo/llm/base.py:33`，不能由协议兼容名称直接断言MiniMax可用。与当前Codex不同模型时，只能比较完整系统组合，不能把差异归因UFO框架。

源码获取曾遇GitHub API403、既有代理不可达、raw路径404/TLS错误；最终通过单命令临时清空Git代理读取固定提交，未改全局代理。失败不作为上游能力判断。补读曾误用processor_framework旧路径，已按manifest确认实际在`core/`下，未据错误路径作判断。

## 最小复用建议

推荐先做一个有界的“接入资格验证”，复用上游Host/App状态机、UIA控件收集、本地dispatcher和原始日志；保留现有需求输入/Schema/评分器，不迁移Hermes、不建通用平台。最少需补四个条件：

1. 新隔离依赖目录，先解析/验证单机启动所需依赖；避免完整清单污染当前项目。
2. 固定模型与配置，只读受控材料；验证一个不含业务答案的模型调用。
3. 纯UIA采集、目标窗口范围、GUI工具白名单；移除CLI/COM/API/跨设备/旧记忆。截图策略需真正绕过，不能只关VISUAL_MODE。
4. 执行前硬预算、逐动作及失败/恢复日志，退出报告纳入15分钟；复用dispatcher边界，不新建服务。UIA复合操作和Sky set_value如何计数须在运行前明文对齐。

这四项是未来最小适配建议，本轮没有实现。若最小适配仍牵涉大量上游核心修改，备选是只借鉴其状态机与控件收集，继续现有Sky路径；优点是成本低，缺点是不能声称已复用UFO完整自主循环。直接安装整套默认UFO适合允许混合GUI/API与截图的任务，与本轮边界不符，暂不推荐。

## 准入判定

当前为`BLOCKED_BEFORE_COMPARISON`：UFO运行依赖/模型兼容未验证，默认观察与工具边界不符，预算语义未对齐；新输入健康检查也只完成被动部分。尚无任一UFO自主探索报告，不能评分、比较优劣或计算成功率。阻碍是本项目约束下的接入工作，不能据此断言UFO不适合Windows软件探索。
