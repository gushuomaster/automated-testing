# Computer Use 宿主连接诊断与恢复交接

## 结论

2026-10-29，用户授权恢复本地 Computer Use 连接。本轮已完成只读诊断，连接尚未恢复。确认的直接原因是：Sky 配置指向上一宿主创建的命名管道，该管道当前不存在；当前宿主日志未发现新 Computer Use 管道就绪记录。尚未证明宿主为什么未建立新连接，不能将直接原因扩大为最终根因。

JavaScript 基础执行正常，Sky 窗口枚举失败；已进行有限重试和 JavaScript 重置，无效。MiniOrder 未启动，GUI 动作为 0。独立健康检查未完成，A/B 均为 NOT_STARTED，正式完成率仍为 0/2。

## 已确认的证据

- `C:\Users\28320\.codex\config.toml:306`：`SKY_CUA_NATIVE_PIPE_DIRECTORY` 固定为 `\\.\pipe\codex-computer-use-6c814b5a-db35-48fb-bf66-bbc04800c8be`；该事实不证明配置是人工还是宿主自动写入。
- 10 月 28 日宿主日志第 140–141 行：北京时间 14:03:37，宿主记录 notify config `status=repaired`，并创建上述同名管道。
- 同日日志第 16395 行：北京时间 18:12:38，记录 helper 退出码 `3221225794`。它是历史异常线索，尚不能确认与今天故障的因果关系，也不依据退出码断言缺失依赖。
- 当前宿主主进程 PID 25236，启动于 10 月 29 日北京时间 09:14:25。当前主日志未匹配到 `computer-use-native-pipe`；10:46 的系统管道枚举仅返回 Codex sandbox、app-tools 和 ipc 管道，没有 Computer Use 管道。
- 昨天和今天启动时均出现 `Appshot hotkey inactive configured=true enabled=false`；昨天随后仍建立了 Computer Use 管道。因此不能把该字段判为本次故障原因。
- 今天存在 `bundled_plugins_reconcile_skipped_features_unavailable`，但未取得足够证据证明它与管道未建立存在因果关系。
- 当前 config SHA-256：`dc47da840392299a7097782dd1f5630664e48469f87502a7dad6528ac3be5c63`。本轮未修改全局配置、插件、执行器或产品。

日志的确切路径、行号和摘录保存在 `artifacts/software-exploration/round-02/diagnostics/host-connection-20261029.json`；其 SHA-256 为 `f058a7bd9b403d586418c17fb24b43b09563a04f5bba1854ef51275ca6bccccd`，另附锁定清单。前次 `uia-connection.json` 和 `diagnostic-lock.json` 原样保留。

## 恢复步骤与边界

当前可用工具中没有宿主 reconnect/restart 接口。普通 JavaScript 重置只重建执行上下文，不能创建桌面宿主管道。没有通过直接启动 helper、修改私有开关或猜测管道地址来绕过宿主。

推荐下一步：用户先保存其他活动任务，在桌面端完全退出 Codex 后重新打开，返回本会话继续。仅关闭会话标签不等于重启宿主。重启用于尝试重新初始化原生连接，尚未验证有效，不保证自动修复配置。当前助手不通过结束宿主进程中断其他活动会话，也不自动化 Codex 自身界面。

恢复后依次检查：

1. 新宿主日志是否记录 Computer Use 管道就绪；配置中的地址是否对应实际存在的管道。若仍无管道，保留新启动日志，进一步排查宿主能力初始化；若有新管道而配置仍是旧地址，再核查宿主配置刷新问题，不直接猜改地址。
2. 在正确 `mcp__node_repl__js` 入口重新初始化 `@oai/sky`，进行一次轻量窗口枚举。失败即停止正式派发。
3. 按 `launch-instructions.md` 的既定协议，在独立诊断上下文执行真实窗口观察、无业务副作用动作和回读。宿主重启不是健康检查通过。
4. 比较实际运行时版本和操作语义；复核冻结清单。健康检查通过后，分别使用新的隔离上下文原样执行 `dispatch/s2-a.md`、`dispatch/s2-b.md`。

使用的 [Computer Use 技能](C:/Users/28320/.codex/plugins/cache/openai-bundled/computer-use/26.1023.50603/skills/computer-use/SKILL.md) 明确要求：`Do not spawn codex-computer-use.exe, search for the helper executable, or build a custom helper protocol client.` 本轮仅检索已有日志，没有寻找或启动 helper 可执行文件。恢复指导见同包 `docs/guidance.md` 的 Recovery；有限恢复已耗尽，不再反复调用必然失败的正式实验。

OpenAI Docs 的官方故障页读取返回 HTTP 403，未获得可支持本故障修复的官方说明；以上判断来自本机证据，不冒充官方确定的产品缺陷归因。

## 实验保护与验证

源码 HEAD：`e0adf976af2674ffd09291a758ac24d11907a6b2`，工作区已有 S2 未跟踪文件，本轮保留。未提交、推送、归档；任务仍为 `in_progress`。

35 个冻结文件逐项复核无漂移，`freeze.json` SHA-256 仍为 `c689bba13f56beaf5f711036a2cee31a059105eeb73a760380692be9dccb7228`。本轮没有改写冻结协议、需求、构建、种子、旧原始报告或旧诊断；不产生能力分数。新诊断为组织方证据，不冒充独立健康检查。
