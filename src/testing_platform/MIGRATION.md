# testing_platform 迁移说明

本目录从 `D:\project\agent\examples` 的 `testing_platform` 有选择迁移，来源基线为：

- Git HEAD：`cc59c6b036d2bda759aec3afef9bb520ec222012`
- 工作区状态摘要：`4f801c5f4ef6a29ba935499007c134ad285d19df5ef8a0f0dd0cb5f3d2751e49`
- 详细复用清单和来源文件哈希：`artifacts/requirement-analysis/baseline/platform-reuse-baseline.md`

首批只迁移 S1 所需的领域模型、Agent/任务/产物/Runner 端口、任务服务、Runner Registry、SQLite Task Repository 和 Local Artifact Store。以下内容没有迁移：Web UI、FastAPI、浏览器 Runner、UI-TARS、Excel 工作流、旧命令入口、历史产物和测试报告流程。

正式代码不得导入或运行 `..\examples`。后续对迁入代码的修改必须在当前仓库完成，并由本仓库测试验证。

