# S2 round-03单次严格Sky探索

本目录为同一样本的development/calibration。仅s2-r03-run01一个独立目标，核验需求输入；不代表S1实际输出端到端复测，不是UFO比较或陌生软件泛化验证。

- `freeze.json` / `freeze-lock.json`：运行前16项确切字节冻结。
- `protocol-base.md` / `protocol-addendum.md`：原评分与本轮计数/干扰停止增补。
- `test-bundle.md`：独立测试方完整可见材料，测试方不读文件，由中性派发方全文传递。
- `isolation.md`：认知/流程隔离及OS沙箱限制。
- `launch-instructions.md` / `capture-protocol.json`：启动、原始捕获与锁后评分口径。
- `final-evaluation.md`：最终状态与范围结论。
- `quality-review.md`：独立质量复核，交付可接受与实验严格失败分开。
- `status-report.md`：简要交付状态，正式报告1/1与严格通过0/1分开。
- `adjudications/`：映射/工具/协议独立裁决及原评分纯函数输出；路径以锁后真实复验为依据。
- `results-lock.json`：质量复核后生成的最终报告、裁决、原始锁和复验锁索引。

原始证据统一在`artifacts/software-exploration/round-03`。正式报告、会话与动作锁定后才作真值评分；路径复验使用独立目录，不回写正式原始报告。

本轮唯一正式尝试已完成。46/46映射与声明层级路径有证据，严格停止条件不满足，不能称S2整体通过；详见最终评估。
