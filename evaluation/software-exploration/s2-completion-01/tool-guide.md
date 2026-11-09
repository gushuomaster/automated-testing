# 固定窗口原生 UIA 工具指南

只启动派发中的固定命令（PowerShell设置UTF-8，Python -X utf8）。工具为逐行 JSON 请求/响应，进程持续到输入结束；用 exec_command 获取 session_id 后，使用 write_stdin 向同一 session_id 发送一行 JSON 加换行。不得重启worker、替换配置或修改入口；同日志目录的独占marker拒绝重复启动。

请求：

```json
{"op":"observe"}
{"op":"act","token":"最新快照token","index":0,"action":"focus"}
{"op":"ack","outcome":"CONFIRMED","reason":"具体的新鲜界面证据及确认了什么"}
```

示例 index 仅说明语法，不是实际控件编号。必须先 observe，独立检查快照，然后才用实际最新 token/index 选择一个动作。每次 act 自带新 snapshot，旧索引与 token 随即失效。不得自动拼接多动作或用脚本自行规划/执行探索。

action可为 set_value（另含字符串 value，空字符串允许）、select、focus、expand、collapse、invoke；仅在 available_actions 存在、当前 enabled=true/offscreen=false 时可用。不得因 exposed invoke 就调用风险按钮。close 仅组织方可用。组合框子选项若未出现，可以先展开后观察；不能猜测选项或用内部值绕过。

snapshot.nodes 含 index、parent、name、automation_id、control_type、value、focused、selected、expanded_state、enabled、offscreen、available_actions、pattern_status、errors。focused 独立取公开 UIA HasKeyboardFocus；不等于 enabled。空值""与null不同，后者可能无Pattern/读取失败。pattern_status=unavailable_or_upstream_com_error 表示可能没暴露Pattern，也可能上游吞了COM错误，不能断言控件不支持或产品缺陷。不可见节点可作观察，不可操作。

每输入返回 ACTION_RETURNED/ACTION_FAILED/TOOL_BLOCKED 和 snapshot，不代表实际行为已确认。state=NEEDS_REVIEW 时不得再输入，需依据新快照 ack：

```json
{"op":"ack","outcome":"UNRESOLVED","reason":"说明为什么实际结果仍未知"}
{"op":"observe"}
{"op":"ack","outcome":"UNRESOLVED","reason":"一次被动复核后仍缺少什么证据，停止"}
```

若被动回读已取得充分证据，可改为 CONFIRMED，并明确依据。程序只检查状态顺序与理由非空，不负责判断理由是否充分；组织方锁后核验，不可滥用确认来绕过未知。STOPPED之后不得输入，不清理、不关闭。工具错误与产品行为分开记录；S2不输出产品缺陷结论。

固定窗口/PID不符、初始化失败、截止或预算拒绝等须如实记录为工具/环境/执行阻塞。原生同步COM无硬中断保障，不无限等候重试。不要调用其他工具或通信求助；在最终JSON中交付当前证据和未知项。
