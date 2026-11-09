# UFO接入探针执行契约

## 1. 适用范围

适用于`scripts/ufo_admission_probe.py`及固定UFO候选接入诊断。此探针不是测试平台或Agent；局部离线通过不能宣布native或完整循环准入。

## 2. 接口

`RestrictedUFODispatcher(native_dispatcher, *, target_window, selected_window, control_window, max_seconds=30, max_inputs=2, max_same_action_retries=2, clock=time.monotonic)`；异步`execute_commands(commands, timeout=6000)`返回原生Result列表；拒绝抛AdmissionDenied，下游显式失败抛NativeExecutionFailed。

## 3. 契约

- native必须仅注册已核验的目标UIA服务器；原生dispatcher不暴露给测试模型。回调从真实UIA取PID/HWND，不信任模型参数。
- 窗口归属不等于无业务副作用；本wrapper不识别保存等业务按钮。真实接入还需限定允许的非破坏性目标，不能单凭白名单宣称持久化副作用为0。
- 白名单仅目标window/controls info、get_ui_tree和单次左键click_input；texts因接收器隐含set_focus不得算零成本读取，直接拒绝。
- 整批预检后串行逐条复查；输入尝试先扣账，失败不退还；相同失败原始一次加最多两次重试。整批预检拒绝时底层callback零调用；逐条复查拒绝只保证该条未调用，先前已执行前缀仍计数保留。
- 时限逐条执行前检查并限制await时间；不宣称能抢占同步Windows线程或计量原生所有焦点/键鼠事件。
- 原生Result success不足以证明业务/GUI状态通过，必须独立回读；吞错、空回读或观察冲突保留不确定。
- 候选模型密钥只在进程内使用，构造器必须使用其配置提供方endpoint、显式超时/重试；禁止把自定义提供方密钥交给默认的另一提供方。记录请求数/用量，price表缺失产生的0不得称免费。

## 4. 错误矩阵

| 条件 | 行为 |
| --- | --- |
| 非白名单、未知参数、复合动作、非目标窗口/控件 | 对被拒命令执行前阻断；整批预检拒绝则整批下游零调用，逐条复查不能抹去已执行前缀 |
| 整批将超过输入上限 | 全批拒绝，不先执行前缀 |
| deadline或失败重试上限到达 | 拒绝下一条，不扩大预算 |
| 下游异常/非success/error/结果缺失 | 已耗动作计数保留，记录失败，停止批次 |
| 同步操作超时后可能仍运行 | 报告执行不确定，不声称已强制停止 |
| 原生依赖/截图策略未打通 | 标记未准入，禁止用mock/Sky替代native通过 |

## 5. 正常、局部与错误案例

正常：超限批次被拒绝，native.calls为空。局部：fake callback33项测试通过，但native依赖缺失，仍未准入。错误：只关VISUAL_MODE或只挡capture命令就宣布全链路无截图；策略内部还可能直接调用PhotographerFacade。

## 6. 必要验证

`uv run python -m pytest tests/unit/test_ufo_admission_probe.py -q`覆盖越权、批次、并发、失败占账、重试、deadline和texts拒绝。实际接入还需原生工具列表、真实归属回调、无截图路径及GUI动作/回读；离线测试不替代这些检查。模型探针不得在质量检查中自动重跑。

## 7. 错误与正确

错误：`if result.status == 'success': business_pass = True`。

正确：保留原生状态，重新观察公开界面，再判断目标状态是否得到证据支持；不足时记INDETERMINATE。`get_ui_tree`等只读观察与会触发set_focus的action分开授权，不能由工具名称猜测是否无输入副作用。
