# M1 换机交接（2026-11-16）

旧电脑：DESKTOP-E4SCU95，内存 15.7 GB。虚拟机占 6 GB，探索运行时空闲内存只剩约 5.5 GB，所以换到新电脑继续。本文件写给新电脑上的 Claude 会话。

## 先读什么

1. 本文件。
2. 同目录的 `prd.md`（目的、真值、度量、验收）、`design.md`（模块、流程、虚拟机执行）、`implement.md`（步骤 1 到 10）。
3. 仓库根目录的 `AGENTS.md`，以及 `.trellis/workflow.md`。

用户偏好：用中文思考和回复；方案要独立复审，不要被已有约束锚定；引入新技术前先搜索已有调研。这些都写在 Claude 记忆里，见下文第 6 节。

## 当前进度

- 分支 `m1-vm-remote-desktop`，最新提交 `7582930`（WIP）。全部 4 个分支已推送到 `origin`（GitHub `gushuomaster/automated-testing`）。
- 单元测试 293 个全部通过（`.venv\Scripts\python.exe -m pytest tests/unit -q`）。
- `implement.md` 步骤 1 到 9 已完成。步骤 10（真实运行）还没有一次有效的完整运行。

| 运行（`artifacts/m1-runs/`） | 结果 |
|---|---|
| `run-01` | 作废：误在本机桌面运行，没进虚拟机 |
| `smoke-vm` | 冒烟测试，小预算只跑了 C1 |
| `run-02-vm` | 只有 C1、C2 有效。C3 到 C6 失败，原因是来宾机远程服务崩溃（`_ctypes.pyd` 访问冲突）。已修复：`kpxc_*` 每个操作改到独立子进程执行（`apps/keepassxc_guest.py`）；修复后连续 5 轮干净循环、5 轮带未保存改动的循环，服务都保持在线 |
| `run-03-vm` | 中断，只有 `plan.json` 和 `charter-1` |
| `run-04-vm-short` | 作废：规划阶段模型 API 超时，没进虚拟机 |
| `run-05-vm-short` | 参数：`--total-actions 80 --total-wall-seconds 1800`。C1 完成（6 条笔记，0 条报告）；C2 到 C6 全部是 `APIConnectionError`，模型中转不可达，不是虚拟机的问题。费用约 1.27 美元 |

- 到目前为止没有产出任何缺陷报告。模型请求走 `ANTHROPIC_BASE_URL` 指向的中转服务，旧电脑最后一次会话也是因为连不上中转而结束的（ENOTFOUND）。`model.py` 已设置 `max_retries=4`、`timeout=120`，run-05 仍然失败，说明中转连续几分钟不可达。
- `run-04`、`run-05` 目录里的 `mem.csv` 是运行期间的主机内存采样（脚本 `artifacts/vm/memwatch.ps1`）。
- 真值：`benchmarks/keepassxc-m1/truth.json` 四条全部是 `pending`。`artifacts/m1-truth/b9765/` 有一次 #9765 的复现尝试截图，没有写结论；`research/repro-*.md` 还没创建。

## 下一步

1. 按下文搭好新电脑环境，跑单测，再 ping 来宾机服务。
2. 先发一个最小模型请求，确认中转稳定，再用 run-05 的参数重跑短测（例如 `run-06-vm-short`）。真实运行要花钱，运行期间也独占虚拟机桌面，**开跑前先问用户**。
3. 待决策（先问用户）：模型连接错误目前会让当前章程记为 `infra_error`，然后继续跑下一个章程，结果是在中转断开时把剩余章程连续耗掉。可以考虑遇到连接类错误时暂停或中止整轮。
4. 短测通过后跑完整流程（默认预算：300 个动作、400 次模型调用、2 小时），同样先问用户。
5. 人工前置：四条候选缺陷在 2.7.6 上逐条复现确认，结果写入 `research/repro-*.md`，再更新 `truth.json`。
6. 运行结束后由人工填写 `judgement.json`，然后用 `python -m testing_platform.autotest.explore --score <RUN_DIR>` 出度量。

运行命令（旧电脑在 Git Bash 里执行，IP 要换成新地址）：

```bash
OUT=artifacts/m1-runs/run-06-vm-short; mkdir -p $OUT
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m testing_platform.autotest.explore \
  --remote <来宾IP>:8765 --total-actions 80 --total-wall-seconds 1800 --out $OUT > $OUT/console.log 2>&1
```

没有 `--remote` 又没有 `--local` 时，入口会拒绝运行。不要在本机桌面跑。

## 新电脑环境搭建

交接包位置：旧电脑共享目录 `\\DESKTOP-E4SCU95\shared\automated-testing-handover\`（旧电脑上的本地路径是 `D:\shared\automated-testing-handover\`）。

| 交接包内容 | 说明 |
|---|---|
| `HANDOVER.md` | 本文件的副本 |
| `automated-testing.bundle` | 全部分支的 git bundle，GitHub 不可用时的备份 |
| `artifacts\` | 仓库 `artifacts/` 的完整副本（约 863 MB，不含 `__pycache__`） |
| `vm\Windows-10\` | VMware 虚拟机目录（59.8 GB，25 个文件，已按字节数核对） |
| `VMShare\` | 虚拟机共享文件夹里属于本项目的部分（来宾机辅助脚本和 `stage\`）；其他项目的文件没有复制 |
| `claude-project\` | Claude 记忆和历史会话 |

### 1. 代码

建议用和旧电脑一样的路径：`evaluation/` 里的证据文件、`task.json` 记录的是绝对路径，Claude 项目目录名也是从路径生成的。

```powershell
git clone https://github.com/gushuomaster/automated-testing.git D:\project\agent\automated-testing
cd D:\project\agent\automated-testing
git checkout m1-vm-remote-desktop
uv sync    # 旧电脑：Python 3.14.3，uv 0.11.1；所有命令用 .venv\Scripts\python.exe
```

### 2. artifacts

```powershell
robocopy \\DESKTOP-E4SCU95\shared\automated-testing-handover\artifacts D:\project\agent\automated-testing\artifacts /E
```

其中有几个运行必需的文件：

- `artifacts/vm/token.txt`：来宾机远程服务的令牌，`explore.py` 默认从这里读。属于密钥，不能进 git。
- `artifacts/vm/guest.json`：来宾账户密码和 `.vmx` 路径，供 `artifacts/vm/vmrun.py` 使用。如果虚拟机放的位置和旧电脑不同，要改 `vmx` 字段。不要把它的内容打印出来。
- `artifacts/feasibility-01/downloads/kpxc-2.7.6/`：主机端的 KeePassXC 2.7.6，含造种子库用的 `keepassxc-cli`。

### 3. 虚拟机

- 旧电脑装的是 VMware Workstation 26.0.0，虚拟硬件版本 22；新电脑需要同版本或更新。虚拟机配置：6 GB 内存、2 个 vCPU、NAT 网络。新电脑内存够的话可以调大。
- 把 `vm\Windows-10\` 复制到本地盘，建议仍放在 `D:\VirtualMachines\Windows-10\`，这样 `guest.json` 不用改。打开 `Windows 10 x64.vmx`，VMware 问“移动还是复制”时，选“我已移动该虚拟机”。
- 共享文件夹：`.vmx` 里写的是 `sharedFolder0.hostPath = "D:\VMShare"`，来宾机里对应 `\\vmware-host\Shared Folders\VMShare`。把交接包的 `VMShare\` 复制到新电脑的 `D:\VMShare\`。
- 状态：虚拟机处于挂起状态（2026-11-13 17:08 挂起），来宾机里的代码是最新的。有两个快照：
  - `Win10-22H2-干净基线`（2026-08-17）
  - `m1-base`（2026-11-13 10:00）：**早于 `kpxc_*` 子进程修复**。回到这个快照后，必须重新同步来宾机代码（见第 4 节）。
- 如果因为 CPU 不同而无法恢复挂起状态：放弃挂起状态，直接冷启动。来宾机配置了自动登录 `autotest` 账户，开机后计划任务 `autotest-remote-server` 会自动启动服务。
- 来宾 IP：新电脑的 VMnet8 网段不同，IP 大概率不再是 `192.168.53.129`。用下面的命令查询，再改 `artifacts/vm/ping_remote.py`（里面写死了 IP）和运行命令里的 `--remote`。

  ```powershell
  & "C:\Program Files\VMware\VMware Workstation\vmrun.exe" -T ws getGuestIPAddress "D:\VirtualMachines\Windows-10\Windows 10 x64.vmx" -wait
  ```

  服务端口是 8765，来宾机防火墙规则已经配好。

### 4. 来宾机布局与代码同步（排障时用）

- `C:\autotest\src`：代码副本（服务以 `C:\autotest\src` 为工作目录运行）。
- `C:\autotest\benchmarks`：种子库。
- `C:\autotest\KeePassXC`：KeePassXC 2.7.6。
- 其他：`C:\autotest\token.txt`（令牌）、`C:\autotest\shots`（截图）、`C:\autotest\server.log`（服务日志）、`C:\autotest\run\state.json`（`kpxc_*` 子进程状态）。
- Python 装在 `C:\Python314`。计划任务 `autotest-remote-server` 以 `autotest` 交互会话运行 `python -m testing_platform.autotest.desktop.remote_server --out C:\autotest\shots --token-file C:\autotest\token.txt`。
- 同步单个文件，然后重启服务：

  ```bash
  .venv/Scripts/python.exe artifacts/vm/vmrun.py copyFileFromHostToGuest <主机文件> 'C:\autotest\src\testing_platform\...'
  .venv/Scripts/python.exe artifacts/vm/vmrun.py runProgramInGuest 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File 'C:\autotest\restart-server.ps1'
  .venv/Scripts/python.exe artifacts/vm/vmrun.py copyFileFromGuestToHost 'C:\autotest\restart.log' artifacts/vm/guest-check/restart.log
  ```

  主机上的源脚本是 `artifacts/vm/restart-server.ps1`。
- **注意**：`D:\VMShare\stage\` 是 2026-11-10 的旧快照（其中的 `agent.py` 和 `remote_server.py` 都比仓库旧），不要用 `stage-copy.ps1` 整体覆盖来宾机，否则会把来宾机上更新过的代码改回旧版。要整体同步，先用仓库 `src/` 重建 `stage\src`。
- `artifacts/vm/desk.ps1`：在来宾桌面会话里运行一段 Python 脚本，再取回结果，用来排查 GUI 问题。

### 5. 环境变量

旧电脑设置了 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_AUTH_TOKEN`（`explore.py` 也接受 `ANTHROPIC_API_KEY`）。它们的值不在交接包里，由用户在新电脑上自己设置。设置完先发一个最小请求，确认中转连得通。

### 6. Claude 记忆与历史会话

把交接包的 `claude-project\` 复制到 `%USERPROFILE%\.claude\projects\D--project-agent-automated-testing\`。前提是项目路径和旧电脑一样，否则目录名会不同。

- `memory\`：用户偏好和项目背景，共 5 条。
- `f9490507-….jsonl`：M0 到 M1 的主会话（21 MB），可以用 `claude --resume` 打开查细节。
- `c6f22c17-….jsonl`：本次交接的会话。

### 7. Trellis 开发者身份

`.trellis/.developer` 被 gitignore 了，旧电脑上的内容是 `name=--help`，是当初初始化时把参数误当成了名字。新电脑上用 `.trellis/scripts/init_developer.py` 重新初始化，名字向用户确认。

## 新电脑环境检查

1. `.venv\Scripts\python.exe -m pytest tests/unit -q`：应为 293 passed。
2. 改好 IP 后运行 `.venv\Scripts\python.exe artifacts/vm/ping_remote.py`：带正确令牌的 ping 应该成功，错误令牌应该被拒绝。
3. 发一个最小模型请求，确认中转可用。
4. 以上都通过后，问用户是否开始跑 `run-06-vm-short`。
