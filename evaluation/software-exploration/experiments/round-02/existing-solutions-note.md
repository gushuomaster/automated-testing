# 软件探索现成方案：当前范围内的判断

2026-10-29。用户询问是否已有项目帮助大模型探索软件。答案是有，应先比较合适方案再决定补什么；本次仅调查，不安装、切换执行器或改变冻结实验。

| 候选 | 已读依据及可帮助的部分 | 当前限制 |
| --- | --- | --- |
| Microsoft UFO² | 官方仓库README明确单机Windows自动化、UIA/Win32/WinCOM、视觉与UIA混合检测、文档/演示/轨迹RAG；可借鉴窗口/应用选择、执行与反馈 | 未在本机实测；混合API动作必须限制，避免绕过GUI黑盒边界；不引入当前不需的Galaxy跨设备编排 |
| UI-TARS Desktop | 本机README.zh-CN.md第234～250行明确本地原生GUI Agent；可作为视觉观察/操作候选 | 当前S2是UIA路线，尚未比较或验证其探索、需求映射及证据能力；不能中途替换 |
| Midscene + midscene-pc | 本机Midscene README第104～108行将Windows/macOS/Linux PC扩展列为社区项目 | 主仓库浏览器能力不能直接当作Windows C/S能力；社区扩展需单独核实版本、许可证、依赖及实机表现 |
| Hermes Agent | 本机README第14、21、23行描述skills、记忆、经验与隔离子任务 | 可借鉴工作流、经验组织，不证明已解决Windows界面定位或需求驱动自主探索；没有据此决定整体迁移 |
| 本地CUA验证资料 | `D:/project/agent/cua-validation/artifacts/reports/CUA-GUI-Execution-Adapter-Fit-Assessment.md`有Windows/UIA/输入的历史实测及限制 | 历史工具实测不能自动代替当前Sky或其他软件验证 |

官方资料核对地址：`https://raw.githubusercontent.com/microsoft/UFO/main/README.md`（本次只读访问成功）；仓库主页 `https://github.com/microsoft/UFO`。README当前内容也包含Galaxy编排，不能把整个项目规模作为本任务必需。

推荐优先评估UFO²单机Windows路径，原因是与当前UIA探索对象最接近；UI-TARS在需要视觉路线时比较，Midscene-PC在其社区设备适配与运行条件合适时比较，Hermes只按所需职责借鉴。推荐是待验证候选，不是已选定替换架构。

需求驱动的最小比较方法：使用同一MiniOrder、同一中文需求、相同初态和动作/时间预算，不提供业务操作脚本；比较能否自主找到入口、建立需求→界面/路径/状态映射、在动作后确认结果、处理冲突、遵守边界及输出可复查证据。另计依赖、启动成本、恢复与人工介入。若现成方案满足，就复用；只补输出契约与证据等确实缺失部分，不先开发通用探索框架。该比较尚未执行，不据README宣布能力通过。
