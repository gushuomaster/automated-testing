# UFO单机纯UIA接入资格结果

2026-10-29。结论：**部分验证完成，完整UFO暂不准入正式比较**。模型调用兼容和现有Sky健康闭环已有实测；UFO完整Host/App、原生UIA执行、全链路禁截图和统一硬预算没有通过，正式比较未启动。不能用局部成功替代整体资格。

## 实际完成

| 项目 | 证据与结果 | 不能推导的结论 |
| --- | --- | --- |
| 隔离环境 | 新建Python3.10.20环境，43个解析后包，约65.4MiB文件；项目与Hermes环境不修改 | 不是完整上游依赖安装成功 |
| UFO模型模块 | 原生ClaudeService导入成功；候选客户端仅补配置endpoint、SDK零重试、60秒超时 | 原版默认客户端不能直接认定兼容MiniMax |
| 真实模型调用 | 经已有MiniMax配置的Anthropic endpoint，1次通用中文请求、HTTP200、返回`{"状态":"可用"}`，JSON可解析 | 未验证完整App/Host响应Schema、复杂规划或模型稳定性 |
| 执行前防线 | 新增小型RestrictedUFODispatcher；33项离线测试通过，禁止截图/CLI/COM/越界/复合输入，失败占账，超预算不调用下游 | fake callback测试，不是已连接真实native dispatcher |
| Sky真实窗口 | 独立诊断上下文150.514秒完成纯UIA空白观察→页签往返→退出确认，4/6输入，工具错误0，种子不变 | 仅现有Sky，非UFO UIA执行或自主探索 |
| 完整UFO | 真实导入dispatcher/basic/aip.Command遇fastmcp缺失，inspector因入口自动注册Excel而遇pandas缺失；源码另见多处截图耦合 | 没有运行完整循环，不能评成绩或说优于现有方案 |

请求上限2次，本次实际只有1次，没有为了探针成功反复换模型/配置。输入只包含通用中文状态指令，不含需求、窗口、业务数据或缺陷答案；密钥仅在进程内使用，未打印/保存。上游PRICES未配置，返回cost=0只是缺少价格映射，**不表示免费**。响应记录原样保留input_tokens=20、output_tokens=7、cache_read_input_tokens=197，不将缓存字段当作额外独立请求。

## 为什么暂停完整接入

这不是“UFO不能探索Windows”，而是固定版本的默认组合不满足本轮狭窄边界。即使关RAG和视觉配置，入口仍有重依赖与多处直接图片采集。继续完整接入需改Host采集、App采集/标注/模型输入/动作后处理、可选依赖及服务器加载等多处路径，超出用户批准的最小验证。没有因此安装整套RAG依赖或写替代Agent。

因此当前不推荐为本次纯UIA实验引入完整UFO。可保留其状态机/控件收集设计作为参考；本次已复用其真实模型服务，但没有把“参考设计”说成“完整框架复用”。详见[接入与边界报告](admission-report.md)。

## 下一步最小建议

推荐回到S2的核心验收：沿用现有Sky，冻结一次严格无干扰的新探索运行，核验需求映射、预算和争议处理，解决此前“报告完成但协议未通过”的问题。已完成的健康检查只支持开跑条件，不保证正式结果。若仍要比较UFO，应单独批准有明确文件清单的多策略纯UIA适配任务，先补全原生执行健康门，再冻结比较，不能在当前轮静默扩大。

## 交付与验证

- 新脚本：[ufo_admission_probe.py](../../../scripts/ufo_admission_probe.py)，仅局部执行前探针；测试：[test_ufo_admission_probe.py](../../../tests/unit/test_ufo_admission_probe.py)。
- 全量pytest **116/116**，其中新边界测试**33/33**；新文件编译、`uv lock --check`通过；OpenSpec strict **3/3**。
- 原始证据位于`artifacts/software-exploration/ufo-admission-01/diagnostics`；候选唯一源码改动及依赖冻结见environment-and-patch.json/candidate.patch及env/requirements-resolved.txt。
- 独立复核、旧锁完整性与本轮新锁见同目录后续清单。本任务仍in_progress，不提交、推送、合并或归档。

本轮未改MiniOrder、业务需求、Schema或评分器。已锁旧任务与报告不回写，所有早期失败保留。本轮属于接入开发验证，不是正式盲测或陌生软件泛化证据。
