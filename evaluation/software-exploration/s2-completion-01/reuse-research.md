# S2 现成项目复用调查（2026-10-29）

结论：优先试用 **Windows-MCP 的 `windows_mcp.uia` 底层作为原生 UIA 工具层**。它已有真正的 Invoke/Value/Selection/Focus 封装，截图不构成调用前提；但公开 MCP 的 Click/Type 仍是坐标/键盘动作，且它没有自主探索 Agent 循环。只复用其 UIA 子包并接一个窗口门禁、观察序列化、动作白名单和现有探索策略，是本次三项调查中最小的可行接入路径。此结论是固定提交源码审查，**不是实机验收通过**。不要求保留 Sky，也不新增平台服务。

## 版本与证据边界

2026-10-29 实际访问 GitHub REST `commits/HEAD` 及 recursive tree，按返回的真实 SHA 下载；未根据项目名推断版本。原始 repo/commit/tree JSON、源码及逐文件 Git blob/SHA-256 校验保存在 `artifacts/software-exploration/s2-completion-01/research/`；`source-manifest.json` 给出逐文件固定链接。README 仅作项目声明，行为判断以代码为准。没有执行下载代码、安装依赖、调模型/凭据或进行 GUI 操作。

| 项目 | 固定提交 | 许可证与复用层级 |
|---|---|---|
| CursorTouch/Windows-MCP | `479bc7f6a5934190477163d98b994db8f9d76b54` | 仓库 MIT；UIA 源文件头另标 Apache-2.0 及 yinkaisheng 原作者。可复用 UIA 工具层，非现成自主 Agent |
| simular-ai/Agent-S | `0fff0e634869dab72027435b4586e62300185d41` | Apache-2.0；同仓库含 S1/S2/S3 及独立 Agent S4 平台，不能把旧 S2/3 当最新整体 |
| TESTARtool/TESTAR_dev | `a5a6eb173765d45c054c1109843f3eaa4425df58` | BSD-3-Clause；现成无源码 GUI 测试探索循环，默认桌面动作并非原生 UIA Pattern |

本地源码前缀分别为 `research/windows-mcp/source/`、`research/agent-s/source/`、`research/testar/source/`，下文路径均相对此前缀。未调查/重复 UFO。

## Windows-MCP：可准入最小 UIA 复用试验

固定上游：[Windows-MCP@479bc7f6](https://github.com/CursorTouch/Windows-MCP/tree/479bc7f6a5934190477163d98b994db8f9d76b54)。

| 需求 | 代码证据 | 判定 |
|---|---|---|
| 不截图观察 | `src/windows_mcp/tools/snapshot.py:38` 默认 `use_vision=False`；`desktop/service.py:279` 只有 `if use_vision` 才调用 capture，`:327` 否则 `screenshot=None` | Snapshot 的截图采集分支可真正不执行，而非只隐藏输出。但 `Screenshot` 独立工具强制 `use_vision=True`（`tools/snapshot.py:97`），应从允许工具集中排除 |
| 原生 Invoke | `uia/patterns.py:534`，`:542` 直接 `self.pattern.Invoke()`；`uia/controls.py:1156` 通用 `GetPattern`，`:3562` Button 的 `GetInvokePattern` | 真正 UIA 原生方法，不需要截图/坐标点击 |
| 原生 Value | `uia/patterns.py:2121`，`:2130` 直接 `self.pattern.SetValue(value)` | 需控件支持 ValuePattern，不能擅自回退坐标/热键 |
| 原生 Selection | `uia/patterns.py:1037`，`:1045` 直接 `self.pattern.Select()` | 需控件支持 SelectionItemPattern |
| 独立 focus | `uia/controls.py:806-812` 返回 `bool(self.Element.CurrentHasKeyboardFocus)`；`:851` IsEnabled 是另一属性；`:1503-1511` SetFocus 调 IUIAutomationElement.SetFocus | focus 不是用 enabled 或窗口前台状态替代；属性读取失败应保留 unknown/error，不能硬填 false。实时可靠性仍需目标应用验证 |
| HWND/PID 限域 | `uia/controls.py:6019` ControlFromHandle；`:959` ProcessId；`:936` NativeWindowHandle；`:1640` GetChildren | 可从已锁定窗口根向下观察并逐动作复核进程/窗口。现成 Snapshot 默认为整桌面，region 是矩形裁剪而非安全的窗口身份隔离 |
| 自主循环 | `src/windows_mcp/__main__.py:255-372` 建 FastMCP 并注册工具；`:521` 启 MCP transport | 这是工具服务层；没有因此获得“自主提出目标、执行、观测、判断终止”的 Agent |

公开 MCP Click 是另一层：`tools/input.py:238` 接收坐标，`desktop/service.py:775-807` 调 `uia.Click/RightClick/MiddleClick`，并非 Invoke；`desktop/service.py:820` 起的 Type 是 SendKeys/剪贴板键盘输入。**不能把“库里有 UIA”写成“现成 MCP 每个动作都原生 UIA”。**

建议接入方式：固定上述 SHA，仅导入/隔离 `windows_mcp.uia`，从已知 HWND 建根；读取 Name、AutomationId、ControlType、Value、IsEnabled、HasKeyboardFocus 等独立字段；只允许 Invoke/SetValue/Select/Toggle/ExpandCollapse/SetFocus 等 Pattern 或原生方法；Pattern 缺失即报告 unsupported。控制动作前复核 HWND/PID 和控件身份，调用后重新观察变化；失败不自动扩大到桌面或坐标回退。只操作可访问性树，不要求被测软件源码、CLI 或业务 API。自绘控件/Canvas 不暴露 UIA 时应明确能力边界。

接入量为“小型适配层 + 探索决策循环”，不是只改一个配置就完整满足。最小外部 Python 依赖从已下载 UIA 子包 import 图看主要是 `comtypes`；`uia/core.py:2030` 的 `wmi` 是单独进程工具函数内延迟导入，原生控件路径不必调用。`windows_mcp/__init__.py` 为空；子包 init 只导入 enums/exceptions/core/patterns/controls/events。`uia/core.py:73-125` 延迟创建 COM，尝试 CUIAutomation8 连接/事务超时，失败降级 CUIAutomation（此时不可宣称仍有相同超时保障）。`uia/comtypes_cache.py` 会维护 COM 生成缓存，不能把直接导入等同纯无副作用读取。

整个 upstream 安装包的要求更重：`pyproject.toml:11` Python >=3.14；`:21-39` 包括 FastMCP、dxcam、Pillow、posthog、pywin32、requests 等。仅做 UIA 子包 vendoring 可避免引入整套服务与截图依赖，但需在实际环境验证兼容性并保存所用版本和许可证；不能宣称上游整包已支持当前 Python。UIA 文件头 `controls.py:1-10`、`core.py`、`patterns.py` 保留 yinkaisheng/Python-UIAutomation-for-Windows 与 Apache-2.0 声明，仓库根 `LICENSE.md` 为 MIT。复制/分发时应同时保留相应声明和许可文本，不能只标 MIT。

## Agent-S：有自主循环，默认路径违反纯 UIA

固定上游：[Agent-S@0fff0e63](https://github.com/simular-ai/Agent-S/tree/0fff0e634869dab72027435b4586e62300185d41)。

当前 S3 `gui_agents/s3/cli_app.py:162-184` 每步无条件 `pyautogui.screenshot()`，保存图像为 observation，再 `agent.predict(...)`；`:215` 执行生成代码。`gui_agents/s3/agents/grounding.py:237-242` 将 `obs['screenshot']` 送视觉 grounding 模型，`:347-368` 生成 `pyautogui.click(x,y,...)`；文本写入也可能先坐标点击、Ctrl+A、剪贴板粘贴（`:428-459`）。该具体路径不能靠关闭图像回传就成为纯 UIA。

`setup.py` 的 console entry 是 S3；安装还包含 OpenAI/Anthropic、paddleocr/paddlepaddle、pytesseract、Selenium、pyautogui、Windows 条件 pywinauto/pywin32 等，Python 声明 `>=3.9, <=3.12`。有模型调用和动作循环，但要换掉观察、定位、动作执行、窗口隔离及生成代码入口才适用，本次没有证据表明存在开箱纯 UIA 模式。

最新树同时出现独立 `agent_s4`：`agent_s4/pyproject.toml:21` 分类 POSIX Linux，`:27-32` 依赖 boto3、dotenv、requests、playwright；README `:3-9` 说明 Builder 在 host 演化接口，task agent 在 fresh AWS VMs 跑 benchmark，`:73-74` 明确 AWS/模型凭据及 OSWorld-V2 需求。这不是小型 Windows 原生 UIA 包。不新增平台服务的约束下，不推荐接入 S4。此处的 S4架构判断中 README 属上游声明，未部署验证。

## TESTAR：现成探索框架，但桌面原生动作需重做

固定上游：[TESTAR_dev@a5a6eb17](https://github.com/TESTARtool/TESTAR_dev/tree/a5a6eb173765d45c054c1109843f3eaa4425df58)。

UIA 观察有实码：`windows/src/org/testar/monkey/alayer/windows/UIAStateBuilder.java:76-116` 创建 UIAutomation 并缓存属性；`StateFetcher.java:306-307` 独立取 `HasKeyboardFocus` 和 `IsKeyboardFocusable`，`:417-418` 分别写 UIATags，`UIATags.java:303` 明确 UIAHasKeyboardFocus。`StateFetcher.java:144-155` 以 SUT PID/配置子进程匹配枚举窗口；这是进程范围，不天然限定单一目标 HWND。`DefaultProtocol.java:746-764` 支持 WindowTitle/ProcessName 连接器，不需要被测软件源码或业务 API。

自主探索循环完整：`testar/src/org/testar/monkey/GenerateMode.java:173-210` 在 moreActions 条件下 selectAction → executeAction → getState → deriveActions；`:70` 外层序列循环。默认动作派生 `testar/src/org/testar/protocols/DesktopProtocol.java:209-244` 是 `clickTypeInto/leftClickAt`；`core/src/org/testar/monkey/alayer/actions/StdActionCompiler.java:111-113` 将控件解析为 WidgetPosition，`:284` 等构造点击加按键动作。UIA 用于观察并不意味着通过 Invoke/Value/Selection 原生执行。下载的 `Windows.java` 有 Pattern ID 常量，未发现对应 Invoke/SetValue/SelectionItem.Select 执行封装，不能以常量名判定支持。

截图关闭尚不满足：`DefaultProtocol.java:825-847` 的 state/action 截图只由 `GraphicsEnvironment.isHeadless()` 分支跳过；`testar/src/org/testar/screenshot/ScreenshotProviderFactory.java` 桌面 DEFAULT_PROVIDER 调 ScreenshotUtil，无发现现成 no-op 配置。已读 SettingsDefaults、desktop_generic/test.settings 未发现显式关闭截图项。`OnlySaveFaultySequences` 控制保存，不等于禁止采集。不应为禁截图直接采用 headless 后宣称真实桌面可正常测试；这需要额外适配及实机验证。

依赖面较大：根 `build.gradle:24-47` 所有 subprojects 引入 Gson、Commons IO、Log4j、Selenium、WebDriverManager、Appium、OrientDB、Graal SDK/JAXB；`windows/build.gradle:11-14` 又依赖 core/Guava，Windows 原生 JNI 层也需匹配。可以关闭状态模型（SettingsDefaults:205），不必启动数据库服务，但整框架仍比 UIA 子包接入重。适用于接受 Java/Gradle 和坐标输入、希望用现成随机/状态模型探索的场景；当前纯 UIA 原生动作优先级下不推荐作为最小实现。

## 本阶段结论与下一步验收

推荐 Windows-MCP UIA 子包作为工具层候选，独立探索循环由项目现有策略或小型新适配承担；Agent-S 和 TESTAR 不作为此次纯 UIA 的直接替代品。上述比较未将“不是完整 Agent”作为排除工具层复用的理由，也未预设保留任何现有框架。

真正验收仍必须在允许的目标窗口上检查：固定依赖可导入、无截图函数调用、focus 与 enabled/value 分开采样、Pattern 返回值与可见状态变化一致、窗口/PID门禁有效、没有坐标/热键兜底、未知/超时可停止。只有这些实机证据才能计入 S2 通过；本文源码证据仅支持选择与适配方案。

网络首次代理失败、raw 超时和一次猜测路径404记录在 `research/network-notes.txt`；已切换固定 SHA 的 GitHub REST 直连，不修改全局代理，未无限重试。

## 收尾核验（2026-10-30）

本次只补齐固定源码完整性和许可证据，未重做上述候选调查，未导入候选代码、启动 GUI、安装依赖或调用模型。逐文件结果见 `artifacts/software-exploration/s2-completion-01/diagnostics/reuse-verification.json`；固定源码、原始 manifest 和历史目录均未修改。

原 `source-manifest.json` 共 106 条，其中 **9 条是导入生成的 `__pycache__/*.pyc`**，并非固定提交中的源码。它们的本地字节虽然符合该清单记录，却不在上游固定 tree 中，其拼出的 GitHub 链接不能作为上游源码证据；已从固定源码核验中明确排除并保留原记录。剩余 **97 个固定源码条目**（Windows-MCP 67、Agent-S 10、TESTAR 20）的字节长度、SHA-256、Git blob SHA-1 均符合清单，且 blob 符合已有固定 `tree.json`。另有 22 个先前下载但未列入 manifest 的源码文件（3 / 2 / 17），本次另列 SHA-256 并核对固定 tree 的 blob，全部相符；不将它们冒充原清单覆盖范围。

Windows-MCP 固定树只含根 `LICENSE.md`（MIT），UIA 的 `controls.py`、`core.py`、`enums.py`、`patterns.py` 第 10 行均保留原作者 yinkaisheng 和 Apache-2.0 声明，**原快照缺少 Apache-2.0 全文**。现已从文件头所指向的原作者仓库补齐独立许可证据：[Python-UIAutomation-for-Windows LICENSE@05cab197](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows/blob/05cab1972d6e08216eae5c5183f9b3d47e26266d/LICENSE)。原始全文保存在 `research/licenses/windows-mcp-uia/Apache-2.0-LICENSE.txt`，11336 字节，SHA-256 为 `75b70e428c22d47d0fb713a5431a0ed07c54c2aadfa6193e386c2b91f9ff4b2b`，Git blob `39254fae5f1cc89a10b22dd6042c96ca96d22628` 与该固定上游树相符；同目录保存 commit/tree/blob 原始 REST 响应与下载链接/哈希。检查了许可正文和附录标记，两个固定仓库树均未提供 `NOTICE` 文件；不能把“未发现 NOTICE”扩大为完整法律审查结论。

因此当前证据包已保存 MIT 根许可、UIA 原声明和 Apache-2.0 全文。后续复制/分发应一并保留这些声明与许可；补充证据不改变上文关于纯 UIA 工具层、窗口门禁及实机验收的限制。许可下载中一次树请求读取超时，固定端点的一次有界重试成功，详情及中文 UTF-8 读写复核记录见同目录 `retrieval.json`。

