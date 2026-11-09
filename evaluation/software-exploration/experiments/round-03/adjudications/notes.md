# round-03 锁后独立映射与运行审计

角色：锁后独立评估方，不是测试方或GUI复验方。只写本目录新增裁决；未操作GUI、未调用模型、未向测试方发消息、未修改原始报告/旧锁/冻结标准/评分器，也未解析内部业务数据。种子只做文件字节哈希核验。

## 锁核验

`lock-verification.json`记录7项exact files大小与SHA256全部匹配。锁总哈希按锁声明的`json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`编码UTF-8、无尾换行后复算，等于`220d929337622e4f5669384a4f6631db631cd24e0b81228d0c75cbbe3ab7c264`。raw-report.json与session task_complete.last_agent_message的UTF-8字节完全相等，43263字节；tool-events共64项，与session原始32个工具调用/32个返回对象逐项相等。freeze.json精确哈希及其16项材料全部匹配。锁先在审查命令中核验，后读真值，记录保存于本目录。

## 映射与控件

`mapping-decisions.json`支持46条正式映射、无unsupported正式映射；每条均含独立reason和session ordinal证据索引。inventory沿原顺序17项均SUPPORTED。30个OBS引用唯一，52个需求编号完整唯一，映射证据引用全部存在。冻结Schema验证0错误。

支持的含义仅为“入口、控件或报告实际声明的安全状态有证据”，不等于需求业务正确性已验证。保存、生成编号、跨重启和目录隔离等未执行行为只支持已声明的入口/安全前缀。REQ-040需求未限定按钮；报告清楚区分手动恢复字段并Return成功与清除筛选按钮调用未确认，故可支持实际路径，不能替换成成功按钮路径。

精确状态46/52匹配。差异为REQ-023/024报告MAPPED而真值PARTIALLY_MAPPED；REQ-037/038/039报告PARTIALLY_MAPPED而真值MAPPED；REQ-045报告INDETERMINATE而真值NOT_UI_OBSERVABLE。这些只属冻结评分之外的状态诊断，不能据此更改46条UI分母/正式映射计分规则。REQ-045仍作非UI分类不一致。

独立GUI复验尚未完成，所有46条path保持PENDING；fully_reproducible_path_ids/safe_prefix_path_ids为空，路径分区明确不完整。未执行最终adjudicate或计算最终路径成绩。原始运行的日志支持不能冒充独立复现通过。另一复验上下文应以报告实际路径层级核验，并保留共享轨迹非独立场景的说明。

## 运行协议

`runtime-audit.json`从完整session逐调用核算：32个顶层functions.exec，其中1个只发现node_repl元数据，31个只转发node_repl+Sky；Sky公开输入为8次set_value、1次失败click、14次press_key，总23。无显式激活；list_apps 1、初次get_window 1、get_window_state 30；后续get_window 0故重绑0；失败click未重试。失败动作和恢复输入均已计入23次。

计划ordinal16在首次GUI输入ordinal33之前。list_apps返回唯一MiniOrder窗口，绑定后的首次被动读ordinal29在任何业务输入前显示四输入字段和金额均无Value，支持可观察空白初态。调用后读取新state，失败click后下一调用仅被动读，没有观察到旧索引跨状态使用。

完整task_started ordinal1(07:37:51.937Z)至task_complete ordinal216(07:46:56.964Z)共545.027秒，即9.083783333分钟。初始NEW_TASK入站ordinal12为07:37:52.006Z，差69毫秒，按较早task_started保守计时。8.5分钟自报少35.027秒，且测试本地计时启动晚16.384秒；最终工具本地计时4.885分钟也不包含完整报告生成。完整时间仍低于15分钟，23次仍低于30次；报告时间不准确与超预算是分开的结论。

入站agent_message仅初始派发ordinal12，运行中无入站消息；未见出站协作/派生Agent调用。初始正文加密，日志只能独立核验发送者/接收者/时间及一次入站，不能逐字证明bundle明文；dispatch-manifest的fork_turns:none及全文确认属于组织记录。未见外部输入警告、异常非空初态或非Agent导致值变化；focused_element冲突在Alt+Down展开和Down选择中交叉核验。没有OS输入钩子/独占桌面，不能称证明绝对无干扰。

## 严格停止规则：FAIL

冻结`protocol-addendum.md`原文：

> 主动输入后一次回读未及时更新不直接认定干扰：先仅被动回读区分时序滞后，不能充分判断则INDETERMINATE并结束。

两处违反此停止条件：

1. OBS-020/021：space查询调用143、即时返回146仍两行；被动调用148/返回151仍两行，报告明确“不能确认该space调用了查询”。随后输入155(Return)继续，而没有结束。
2. OBS-024/025：space清除筛选调用167、即时返回170未清理；被动调用172/返回175仍保留筛选，报告明确按钮路径不确定。随后输入179/184/189手动恢复字段并刷新，未结束。恢复成功不消除先前偏离。

这是对无法判明动作结果的严格停止条款的适用，不把未变化本身或focused_element冲突视为外部干扰。Return收起列表(110→113→被动120)及最终Ctrl+Tab(198→201→被动208)则在被动读中判明滞后，分别属于已解决情形。测试正确报告了未决结果，但如实报告并不等于满足“并结束”。因此strict_protocol_pass=false；不能因为映射或未来复验分数高而放宽冻结规则。

## 工具分类与副作用

原始日志足以核验30个报告OBS的工具状态，独立逐项裁决30/30正确，覆盖失败几何输入、焦点元数据不可靠、两次已解决回读滞后和未确认按钮结果。该诊断分母是报告OBS单元，不是23次输入，也不是整个OS底层事件；不是新增冻结通过门槛。工具分类正确、严格停止不合规、业务映射支持是三个不同结论。评分器中“没有独立日志所以INDETERMINATE”的遗留固定文案不适用于本轮实际审计，未修改评分器。

无save/delete调用；冻结订单种子文件在运行后字节哈希匹配，且组织结束记录确认相同。结论仅限冻结持久化订单种子和公开GUI动作，不扩张为整个OS任何副作用均为0。

## 验证与编码

交付的JSON再次按UTF-8解析、无BOM，原始7项锁再次核验。一次读取中Python默认stdout使用本机编码导致显示乱码，立即停止该读取路径，改为`python -X utf8`并以“UTF-8复核：中文正常”最小输出核验；未改动原始源文件，也没有替换乱码字符。后续新文件均显式UTF-8无BOM写入。
