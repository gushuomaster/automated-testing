# 未决结果停止规则：最小修正与局部验证

本次已完成通用停止指令修正、只读审计和离线回归；没有启动新正式实验，也没有证明新Agent已可靠停止。round-03的正式报告1/1、严格通过0/1保持原样。

## 修改与原因

实际Sky路径是独立Agent直接通过node_repl调用工具，没有工程内动作循环执行器。UFO限制包装器不在此路径且完整UFO未准入，因此没有改它或新增未接入的gate来声称物理阻断。

- 新增`docs/software-exploration/stop-decision-card.md`：动作结果未知时只允许一次纯被动复核；仍未知就记INDETERMINATE并结束GUI，不再替代按键、重试或自行清理。锁后由评估方另行恢复，保留残留状态和责任边界。
- 保留焦点字段冲突例外：仅focused_element不一致可在原许可/预算内用另一界面行为核验；不单凭该字段判断干扰或产品缺陷。状态不变也不自动等于未知，确认合法不变与真正证据不足须区分。
- 新增`scripts/audit_exploration_stop.py`与47项单测：读已有独立评估方人工核验的调用目录，再读显式语义检查点，核对时序、输出配对、纯被动复核及后续输入。缺失/非法依据拒绝，清理输入不豁免，输出文件拒绝覆盖。没有NLP关键词猜测、GUI动作或模型调用。
- 新增独立执行契约`.trellis/spec/backend/exploration-stop-audit.md`，由任务文档引用；为保全UFO既有锁定索引，未修改旧backend/index.md。

新代码位于`scripts`，不修改被测程序、需求、Schema、原评分器或Sky执行器，不新增服务/Runtime/依赖。OpenSpec既有实现与规范未改；本次作为Trellis中的局部开发回归任务交付。

## 事先固定的真实回归

`validation-plan.md`与`regression-checkpoints.json`在运行新审计前固定预期。输入来源、源码HEAD、工作区状态及旧锁哈希见`artifacts/software-exploration/stop-rule-calibration-01/baseline.json`。仅复用旧材料作为development/regression，不是新Agent自主发现。

|检查点|审计结果|解释|
|---|---|---|
|input110 / output113 / 被动117→120|CONFIRMED_CONTINUATION_ALLOWED|滞后在被动读中解决，该点不触发停止|
|input143 / output146 / 被动148→151|STOP_RULE_DEVIATION|应在151后停止，续输155、162、167、179、184、189、198|
|input167 / output170 / 被动172→175|STOP_RULE_DEVIATION|该点仍未决，后续179、184、189、198含清理输入|
|input198 / output201 / 被动205→208|CONFIRMED_CONTINUATION_ALLOWED|该点本身滞后已解决，不撤销151起的旧停止要求|
|input88 / output91，仅focus字段冲突|FOCUS_METADATA_EXCEPTION|允许其他许可界面行为核验，不单独判停止或产品缺陷|

两处偏离全部检出（2/2已审未决点）；两处已解决滞后与一处focus例外未被该规则误判（3/3已审非终止点）。最早截止为output ordinal151，最早违规输入155。不同未决点后的续输集合有重叠，不能加成11次独立违规；最早截止后目录内共有7次唯一输入。ordinal是原记录字段，不是文件行号。

CLI返回1并正常写出`artifacts/software-exploration/stop-rule-calibration-01/regression-result.json`，表示检出旧偏离，不是工具执行失败。输出附两份输入的SHA-256。原报告和成绩没有改写或重算。

## 验证

- 实现方局部单测47项通过；覆盖真正结束、确认前续输、未决后清理、工具成功但结果未决、滞后解决、focus例外、非法/空输入、引用配对与输出防覆盖。
- 仓库`.venv/Scripts/python.exe -m pytest -q`：163项通过。
- 新Python文件compileall通过；`uv lock --check`通过，未改依赖。
- `openspec validate --all --strict --no-interactive`：既有3项全部通过，未新建或修改OpenSpec实施项。
- 初次全量测试误用系统Python3.14，因缺testing_platform/docx出现9个收集错误；使用现有项目.venv后全量通过。未安装依赖，不将该收集失败归为产品缺陷或删除失败经过。
- 历史锁前置核验：UFO290/290、方案调查55/55、round-02结果21/21及冻结35/35、round-03结果39/39及冻结16/16。最终复核与UTF-8/JSON检查见`verification.json`；质量审查见`quality-review.md`。

独立复核产生的`artifacts/software-exploration/stop-rule-calibration-01/quality-unit-tmp`临时目录清理被自动审批拒绝（仅返回`blocked by policy`），未尝试绕过，目录保留；不作为必要交付证据纳入新锁。

## 能支持与不能支持的结论

支持：停止指令已消除“清理优先还是停止优先”的歧义；审计在5个预先固定人工检查点上与旧独立裁决一致，能列出继续输入证据，同时保留已解决滞后和focus例外。

尚不能支持：新Agent会可靠执行该指令、工具层已经阻断输入、完整日志无遗漏、人工语义裁决自动正确、S2严格流程通过。局部无偏离的退出0只适用于给定检查点与提供目录，不是全协议PASS。脚本不从旧原始会话自动提取全部动作，不自动判断业务语义，也不改变旧评分。

下一最小验证应在未来获授权的新独立上下文中冻结并使用通用决策卡，专门观察结果未决时是否真实结束；具体旧案例与答案不提供给测试方。本轮到局部修正验证为止，不自动启动下一轮、不进入S3、不提交推送归档。若最终需要物理强制停止，应先界定当前直接Sky调用的接入点；不能把本次只读审计当执行器。
