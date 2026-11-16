# M1 执行计划

所有 Python 命令用项目虚拟环境：`.venv\Scripts\python.exe`（系统 Python 没装 `testing_platform`）。每一步完成后跑该步的验证命令，通过再进入下一步。

## 步骤

1. **defects.py：报告与笔记校验**
   - 实现 `parse_report_defect`、`DefectReport`、`NoteBook`、每章程条数上限。
   - 先写测试（缺字段、空步骤、非法严重度、超上限、笔记过长），再写实现。
   - 验证：`.venv\Scripts\python.exe -m pytest tests/unit/test_autotest_m1.py -q`

2. **agent.py：可选的框架内工具**
   - `Agent.__init__` 增加 `system_prompt`、`extra_tools`、`handlers`，默认值保持 M0 行为。
   - `_observation_content` 后记录 `last_obs`；循环里 `handlers` 命中的工具不占动作预算、不触发新观察。
   - 同一轮动作之后的 `report_defect` 不接受，提示先看观察。
   - 验证：`tests/unit/test_autotest_m0.py` 原样全部通过（行为不变的证据），再加新测试覆盖带 handlers 的路径。

3. **explore.py：规划**
   - 读取手册，调用模型强制 `submit_charters`，校验章程数量和字段，失败直接报错。
   - 验证：用假模型的单测（合法输出、缺字段、章程数超范围）。

4. **explore.py：章程执行与预算**
   - 复用 `benchmark.run_task` 的 reset、launch、Agent、stop 流程，每章程新上下文，携带前序笔记。
   - 总预算用尽后剩余章程标记 `skipped_budget`；单章程出错记录后继续下一章程。
   - 验证：用假桌面和假环境的单测（笔记传递、总预算跳过、单章程异常不中断）。

5. **explore.py：汇总与去重**
   - 一次无工具模型调用做重复分组；失败时保留全部报告并标记 `undeduped`。
   - 验证：假模型单测（正常合并、调用失败降级）。

6. **explore.py：`--score` 度量**
   - 读 `reports.json`、`truth.json`、`judgement.json`，算召回、精确率、覆盖、成本；未判定报告单列。
   - 验证：构造小数据集的单测，手算对照。

7. **探索系统提示**
   - 写入 `explore.py`，单测断言不含 `truth.json` 里任何症状词。

8. **M1 种子库与手册副本**（需要真实环境，非单测）
   - 用 `keepassxc-cli` 造 `benchmarks/keepassxc-m1/seed.kdbx`（根群组和子群组条目，含 TOTP 条目），生成方法写进该目录 `README.md`。
   - 复制四份手册节选到 `manual/`。
   - 验证：`keepassxc-cli export` 能读出预期条目；`parse_export` 解析结果与设计一致。

9. **全量检查**
   - `.venv\Scripts\python.exe -m pytest tests/unit -q`，应在原 244 个基础上只增不减。
   - `git diff --stat` 确认改动范围只在上述文件。

10. **真实运行**（需用户确认：会调用模型 API，且占用桌面，运行期间不能动鼠标键盘）
    - 先用单章程小预算冒烟，再跑完整流程。
    - 产出 `reports.json`、`report.md`、`summary.json`，如实记录成本。

## 人工前置

- 四条候选缺陷在 2.7.6 上的复现确认，由组织方完成，结果写入 `research/repro-*.md` 并更新 `truth.json`。不阻塞 1 到 9 步，但阻塞度量的最终结论。
- `judgement.json` 由人工在真实运行之后填写。

## 回滚点

- 第 2 步改动了 M0 共用的 `agent.py`：任何一个 M0 测试失败，先回退这一步的改动，不要改 M0 测试去迁就新代码。
- 第 8 步造种子库失败：改用 XML 导入或一次性 GUI 辅助脚本，不要手改二进制文件。
- 真实运行前所有步骤都不依赖 GUI 和模型 API，可以随时重跑。

## 完成标准

- 全部单元测试通过，M0 的 72 次运行基线所依赖的行为不变。
- 设计里“待验证”两项已有结论，写入 `research/`。
- 真实运行完成一次，度量和报告如实写入产物目录。
