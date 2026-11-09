# 原生接入与执行边界

2026-10-29。固定上游`microsoft/UFO@eae3c0a8d168c47cb10df0652e293e092eda1078`；候选在`artifacts/software-exploration/ufo-admission-01/candidate`，旧锁定副本只读。主仓库HEAD为`e0adf976af2674ffd09291a758ac24d11907a6b2`，有既有未提交文件，不能把HEAD独自当作完整工作区版本。

## 真实导入和依赖

`diagnostics/import-probe-01.json`保存初次成功导入openai、pywinauto、ufo.llm.openai，及dispatcher/basic缺fastmcp、inspector缺pyautogui的原始错误。补入有界的anthropic/pyautogui/requests/html2text后，`import-probe-02.json`确认原生ClaudeService导入；inspector仍经`ufo.automator.__init__ → app_apis.factory → ExcelWinCOMReceiver → pandas`失败。`native-command-import.json`进一步证明只导入aip.Command也会走MCPServerManager并需要fastmcp。

没有将同名PyPI包aip/galaxy作为本地源码安装。aip从固定提交展开到候选；第一次组织脚本错误拼接cwd、随后promisor缺blob触发既有死代理，均保留记录。单条Git命令覆盖代理后展开成功，不修改全局代理。原始工作树文件保持，Git对象缓存补全不等于改源码。旧源码/调查锁仍需按字节核对。

fastmcp+websockets dry-run还会新增40包；本轮没有执行该安装，更没有启动新服务。完整依赖不是只缺两个名称：BaseSession顶层ExperienceSummarizer引入LangChain/FAISS，App策略顶层grounding引入gradio_client，local server加载还牵涉跨设备galaxy。本轮停止按缺包逐个扩大安装。详细固定路径/行号见`diagnostics/native-path-review.md`；其中142模块是含可选分支的保守静态图，不是实际必装清单。

隔离环境与主项目requires-python>=3.11不同，是刻意为固定上游旧依赖建的独立3.10环境，不修改主项目版本要求。安装后文件约65.4MiB，未安装torch/FAISS/LangChain。没有网络字节限流计量，因此不能把设计中的150MiB目标说成已实施硬下载上限；解析与安装范围受显式包清单约束，解析后43包冻结留存。

## 真实模型与候选最小修改

已有Hermes配置使用MiniMax-M2.7及`https://api.minimaxi.com/anthropic`。固定UFO的`ufo/llm/claude.py`原版构造器只传api_key，会忽略配置API_BASE；若不修正，不能把MiniMax密钥交给其默认的另一提供方。候选只在该构造器补`base_url`、`max_retries=0`、`timeout=60`，没有修改模型规划/消息转换算法。补丁与前后哈希留存，原始副本不改。

离线mock检查确认这四个客户端参数准确传递、不发请求。真实调用使用候选原生ClaudeService.chat_completion和process_messages，原生MAX_RETRY设1代表只尝试一次，SDK重试0，max_tokens=512，n=1。只发送`只返回一个JSON对象：{"状态":"可用"}。不要其他文字。`，实际一次请求成功。原生client的响应hook只保存状态、模型、token用量、内容类型和文本块，不保存请求头、凭据或思考块。

这是**候选原生服务的文本/简单JSON兼容**，比独立SDK探针更直接，但没有启动Host/App，也没验证其完整响应Schema。不能称未修改原版已经兼容，不能由一次HTTP200推导长期可靠。模型probe源码和结果均留存，复核时不得重跑以免再次消耗模型请求。

## 局部防线的保证与不足

新增`RestrictedUFODispatcher`兼容原生execute_commands形状，作为执行前适配器，**本轮只用fake callback验证**。固定目标PID/HWND，由受信实时窗口/控件归属回调核对，拒绝命令自报窗口。仅允许目标info/tree的数据采集与明确单次左键click_input。截图、桌面枚举、选别的窗口、CLI/COM、键盘、值替换、坐标、双击和批量嵌套动作均拒绝。

`texts`原拟作为零成本读取，但原生action接收器会先set_focus，所以复核时移出白名单；新测试确认它不会到达下游。33项测试覆盖越权零调用、批次整体预检、失败占用输入预算、原始一次加最多两次失败重试、截止前阻断后续、并发不能重复消费最后一次输入。该修正属于接入开发，不修改任何已锁正式评分。

执行前计数针对获准单击调用尝试，不证明所有底层焦点/键鼠事件都已计量。窗口/控件归属检查也不判断业务副作用：同窗口的保存按钮仍可能修改数据，不能仅凭此wrapper保证持久化副作用为0；实际接入还需限定允许的非破坏性目标。原生ControlReceiver还会吞掉atomic_execution错误并无条件返回单击成功文本，所以原生success不等于GUI结果成功；必须回读。asyncio timeout也不能抢占已开始的同步UI线程。本轮没有接通native dispatcher、锁定实际工具注册列表/回调或切断多处直接截图调用，故全链路纯UIA与严格停止仍不满足。

## 独立Sky健康检查

新诊断上下文先完整读取computer-use文档并准备就绪，之后才启动唯一新目录MiniOrder和5分钟墙钟。2026-10-29北京时间14:45:14.838开始，14:47:45.352确认退出，150.514秒，4/6输入。初态业务编辑字段未暴露Value；Ctrl+Tab到查询，再Ctrl+Tab返回；返回即时UIA仍为查询，延后被动回读确认新建页，未补按键。退出即时清单也短暂含窗口，延后确认0，未重复退出。

这说明本次Sky最小观察→操作→回读在预算内完成；也提醒即时观察并非动作完成的同步屏障。无工具错误、业务文本输入、保存或种子改变。独立agent原始日志、报告、启动协议和哈希审计在`diagnostics/health-01`。该健康检查不替代UFO native健康、不证明OS独占或自主探索，也不能消除旧实验异常。

## 准入决定

`NOT_ADMITTED`：依赖仅部分可用；模型通用文本兼容通过；局部防线离线通过；Sky健康通过；UFO原生UIA健康、完整循环、无截图、统一硬预算均未通过。正式比较`NOT_STARTED`，没有新成绩或优劣排名。当前证据足以说明整套适配超出本次最小范围，建议先用现有Sky完成严格S2验收。
