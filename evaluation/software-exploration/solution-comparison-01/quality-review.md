# 独立质量复核

2026-10-29。结论：本轮调查报告的主要结论与已保存证据一致，可作为候选接入调查交付；这不表示正式比较准入、健康门或UFO运行通过。正式比较保持 `NOT_STARTED / BLOCKED_BEFORE_COMPARISON`。

## 范围与方法

复核者为独立 `trellis-check` 子Agent。读取项目AGENTS、任务prd/design/implement/check.jsonl及需求分析契约；逐份读取本目录index、状态、输入隔离、可行性、协议、启动材料和integrity文件，对照上游固定副本、manifest、环境探测与三次诊断原始记录。直接按实际文件字节计算SHA-256，不仅复述integrity内的布尔结论。仅新建本文件，未修改旧证据、其他报告、产品、Schema、评分器或依赖。

| 检查 | 独立结果 |
| --- | --- |
| round-02 freeze.json与freeze-lock.json | 冻结文件本身的哈希匹配；直接读取freeze清单，35/35文件哈希及字节数匹配 |
| results-lock-revision-01.json | 21/21文件哈希及字节数匹配；沿用该修订，不误用已说明20/21的旧results-lock |
| 固定UFO源码 | HEAD为 `eae3c0a8d168c47cb10df0652e293e092eda1078`，git status --porcelain为空 |
| source-manifest.json | 18/18文件哈希与字节数匹配，166/166个一基行号的完整文本匹配 |
| 三次诊断EXE/种子 | 每个目录的EXE与orders.json分别匹配冻结EXE及种子哈希，3/3成立；只算哈希，未读取业务数据内容 |
| 当前仓库HEAD | `e0adf976af2674ffd09291a758ac24d11907a6b2`，与报告一致 |
| 报告编码/JSON | 本目录文本严格UTF-8读取、JSON解析成功，未见替代字符；未运行产品测试或评分 |

## 关键事实核对

- 旧结果仍为报告2/2完成、严格协议0/2通过；旧A的an及B的i/z2与外部输入提示不能确认操作者。新报告没有将旧结果当无干扰对照或认定产品缺陷。
- gate02原始tool-events中，两次UIA客户值为1；此前仅激活，没有文本输入。human-input-adjudication明确限定用户自述适用于本次gate02，保留原finish的proven_cause=null，不倒推旧事件。这是保存的用户自述记录与UIA互相支持，不是OS归属取证。
- gate03预注册5分钟/6动作，只有一次激活、两次空白UIA观察、零文本输入及一次退出；没有第三次观察、数量写入/清空回读。finish明确INCOMPLETE_TIME_BUDGET，报告没有宣称健康门通过。
- gate03截止为14:20:44.427；退出按键返回后的记录为14:20:49.860，窗口消失确认为14:21:02.108，分别晚5.43秒和17.68秒。注意代码在await press_key之后取时间，没有按键调用开始时间；可确认记录及退出确认超时，不能仅凭它确定按键开始发送时刻。
- UFO App processor组合截图与控件收集策略；App strategy无条件调用窗口截图，Host strategy无条件调用桌面截图；prompter的is_visual只控制消息附图。这支持“关VISUAL_MODE不足以禁止采集”，未冒称已完成纯UIA适配。
- mcp.yaml的Host/App default均包含CommandLineExecutor，应用专用配置含COM；system.yaml默认USE_MCP=True。移除工具并核对实际列表是有代码依据的后续准入要求，当前没有实机白名单验证。
- MAX_STEP计处理步数；processor_framework递增round/session step，controller.set_edit_text有清空、输入与多级恢复，dispatcher默认6000秒等待，模型默认MAX_RETRY=20。报告正确区分这些值与15分钟/30次GUI动作/最多2次重试，未用静态配置冒充统一硬预算。
- 固定入口提供normal/request，SessionFactory将normal导向Windows Session，其构造使用LocalCommandDispatcher；basic.py包含状态执行循环。支持单机自主循环这一静态结构结论，不能证明本需求已完成探索、需求映射、锁或评分。
- 本地环境、Hermes配置及凭据只核对已保存的存在性和版本探测，没有读取凭据值。报告明确MiniMax与UFO兼容性及成本未验证，不把OpenAI服务入口等同兼容成功；不同模型只允许系统组合层面的解释。
- 协议明确仍为DRAFT_NOT_ADMITTED，实际工具、模型、预算适配和健康门待补齐；中性模板不包含具体业务探索路径或缺陷答案，没有新成绩或优劣判断。

## 复核期间发现与处理

初读runtime-probe时仅有py -3.10失败记录，无法支持“本机已有3.10”。该证据缺口已先报告主方；主方随后补入uv inventory及显式绝对路径探测，3.10.20和3.11.15均exit0，报告补充launcher不能匹配uv runtime的限制。复读后此项已解决：有runtime不等于所需依赖已经齐备，后者仍未验证。

已向主方建议精确区分gate03的退出调用返回记录与调用开始时间；主方已修正输入调查文本及本轮未锁定的派生finish字段为exit_action_return_recorded_at，复读确认一致。此限制不改变“未完成输入回读、未在预算内完成退出确认、不能通过健康门”的结论；原始tool-events及旧gate01/02 finish均保留。当前没有未解决的报告事实问题。

## 未核验与最终锁边界

本复核不运行GUI、UFO、模型API，不安装或解析完整依赖，不验证模型可用性、纯UIA适配、硬预算实现、真正独占输入、完整日志出口或跨软件泛化；也不能从保存记录独立还原旧事件操作者或证实所有历史操作均被完整采集。环境版本及凭据存在性结论依赖保存的探测日志，未重新读取敏感配置。

本次未改产品代码，未重复无变化的lint/typecheck/业务测试或执行评分器。哈希一致只证明当前字节与已保存锁一致，不额外证明最初证据来源的真实性。新evidence-lock尚待主方在复核结束后生成；本复核没有提前声称它已存在或通过。生成后必须再按最终文件字节验证，并继续区分调查证据锁与尚未生成的正式比较冻结。
