# S1 需求解析使用说明

## 能力边界

当前实现摄取 Markdown、DOCX 和带文本层的 PDF，输出 Document IR、原子需求候选、需求基线、歧义、冲突、测试类型建议和双层核验结果。它不生成测试项、测试用例或 GUI 操作计划。图片、扫描页、公式和 DOCX 嵌入对象只登记限制，不声称已理解。

Hermes 是外置运行时，不在项目 `uv.lock` 中。运行真实模型预演前，执行环境必须安装并配置兼容 Hermes；本仓库的领域、解析和评分代码不导入 `D:\project\agent\examples`。

## 本地验证

```powershell
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Resolve-Path src).Path
.\.venv\Scripts\python.exe -m pytest -q
openspec validate build-requirement-analysis-s1 --strict
uv lock --check
```

## 不计分预演

以下命令使用独立子进程并在 180 秒到达时终止。每次运行创建新 UUID 目录，保存输入、Document IR、已完成阶段的输入/响应、日志、失败或完成状态以及报告锁，不覆盖旧结果。

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Resolve-Path src).Path
& '<已安装 Hermes 的 Python>' scripts/run_requirement_prerun.py docs/miniorder/MiniOrder-Requirements.md --role calibration --timeout-seconds 180
& '<已安装 Hermes 的 Python>' scripts/run_requirement_prerun.py 技术要求.docx --role development --timeout-seconds 180
```

预演入口还允许显式设置 `--max-turns`、`--max-output-tokens`、`--max-window-chars`、
`--max-window-segments`、`--max-agent-input-chars`、`--max-consolidation-candidates` 和
`--max-verification-requirements`。阶段输入字符上限默认是 450,000，超限时在调用
Agent 前失败，不截断输入。上述参数会写入 `run-start.json` 并传给隔离子进程，便于在重跑前固定预算；
不得在看到运行结果后回写或隐瞒参数。正式盲测使用单独冻结的协议，不能直接沿用预演调参结果。

大型材料可使用 `--disable-revision` 禁用完整基线自动修订。该开关不会忽略核验问题；问题仍写入锁定结果并进入评分，只是不再要求模型一次返回另一份大型完整基线。

`calibration` 和 `development` 的结果不计算正式精确率或召回率。`failure.json` 的工具/模型失败不能解释为需求资料失败。

若开发预演仅在 `repair` 阶段失败，可从该次锁定运行继续执行修订和修订后核验，不会重新解析、提取、归并或运行初始语义核验：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Resolve-Path src).Path
& '<已安装 Hermes 的 Python>' scripts/run_requirement_prerun.py --resume-from artifacts/requirement-analysis/preruns/development/<父运行 UUID> --role development --timeout-seconds 1200 --max-turns 4 --max-output-tokens 48000
```

续跑前会验证父运行 `report-lock.json`、父运行角色及 `failure.json` 中的失败层；只有锁完整且失败层为 `repair` 才会调用模型。续跑会创建新的 UUID 目录，记录父运行路径、父锁哈希和当前修订/核验提示哈希。父运行及其报告锁保持不变；续跑结果仍属于不计分预演。

当前已完成的 MiniOrder 校准运行是
`artifacts/requirement-analysis/preruns/calibration/3960ded9-e5fc-4079-a214-d9ee43e4a74f`；
《技术要求》的初始开发运行为
`artifacts/requirement-analysis/preruns/development/350f1b80-5467-4188-8597-a9007888da21`，
阶段恢复结果为
`artifacts/requirement-analysis/preruns/development/7a7166bb-46b6-4508-b80d-26f7f21147a5`。
恢复运行保留初始基线并完成修订及修订后两类核验。语义核验的 `96/96 supported` 是模型核验结果，
不是人工真值准确率；MiniOrder 与《技术要求》也不合并成一个总体成绩。

## 产物解释

- `input-manifest.json`、`document-ir.json`：冻结输入及可追溯片段。
- `stages/*-input.json`、`stages/*-response.json`：阶段输入与原始响应证据；可能较大，不应直接提供给正式盲测 Agent。
- `requirement-baseline-initial.json`：初始需求基线。
- `requirement-baseline-revised.json`：最多一次修订后的基线；若存在，仍保留初始版本。
- `deterministic-verification.json`、`semantic-verification.json`：确定性和独立语义核验，修订后会再次执行两类核验。
- `report-lock.json`：运行目录文件的字节数和 SHA-256；锁定后的修改必须新建版本。
- `stages/extract-N-source-normalization.json`：仅当模型选择了有效 `segment_id`、但机械抄错路径、SHA-256 或 locator 时出现；记录由 Document IR 恢复的字段。原始 `extract-N-response.json` 不会被覆盖。未知片段或非连续原文摘录仍会失败。

需求提取窗口只包含有文本且状态为 `parsed` 或 `partial` 的片段。`unknown`、`empty` 和无文本
分页标记仍保留在 `document-ir.json`、`parse-failures.json` 及归并上下文中，用于显式报告解析限制，
但不会作为业务文本要求模型解释。

## 正式盲测

v6 已使用合法、独立且未参与开发调整的匿名 Markdown 材料完成一次正式盲测。评估侧在运行前冻结了材料、双人真值、匹配规则、模型、Skill、提示、预算、隔离清单和实现/环境哈希；正式运行目录、报告锁、锁后评分及适用范围见 `artifacts/requirement-analysis/formal-round-02/assessment-v6.md`。测试 Agent 只能读取材料、通用 Skill、输出 Schema 和预算，不能读取真值、历史答案、源码、预演记录或评分日志。

原始输出锁定后，评估方才能计算逐类别精确率/召回率、F1、来源定位有效率、无依据输出比例和关键保真错误。校准、开发或历史回归结果不得改名混入正式成绩。

## 已知限制

- Windows 本地契约测试和 Debian/glibc 容器的非模型测试已通过；Kylin 尚未实测。
- 真实 Hermes 已完成小材料、MiniOrder 校准集和《技术要求》开发集的预演闭环；v6 正式盲测也已在一份短中文 Markdown 材料上达到冻结门槛。该结果只支持当前样本和格式范围，不能外推为 DOCX/PDF、大文档多窗口、跨块裁决、OCR、图表或多次运行稳定性已经通过。
- 来源确定性规范化已经在新的《技术要求》真实模型运行中生效；它只修复确定性来源元数据，不修复改写摘录或遗漏条件。
- 当前隔离是输入、目录和 Agent 上下文隔离，不是 OS 级安全沙箱。
- PDF 不保证多栏阅读顺序或视觉表格结构；DOCX 不提供 Word 渲染后的可靠页码。
