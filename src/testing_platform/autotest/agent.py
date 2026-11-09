"""Agent loop: model chooses GUI actions through custom tools; the framework enforces budgets.

Every action is followed by a fresh observation (element list + annotated screenshot) returned
in the tool result. Budgets (actions, wall time, model calls) are enforced here, not by prompt.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .desktop.client import ServiceError, ToolTimeout
from .desktop.observation import format_observation

FINISH_STATUSES = ("completed", "failed", "blocked")

TOOLS = [
    {
        "name": "click",
        "description": "点击一个控件或截图上的一个点。优先给 element_id（来自最新观察的 [eN]）；"
                       "控件列表里没有的目标再给截图像素坐标 x、y。",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "最新观察中的控件编号，如 e12"},
                "x": {"type": "number", "description": "截图像素横坐标（无 element_id 时使用）"},
                "y": {"type": "number", "description": "截图像素纵坐标（无 element_id 时使用）"},
                "button": {"type": "string", "enum": ["left", "right"], "description": "默认 left"},
                "double": {"type": "boolean", "description": "是否双击，默认 false"},
            },
        },
    },
    {
        "name": "type_text",
        "description": "向当前焦点输入文本（原样输入，不解析快捷键）。给 element_id 时先点击该控件再输入；"
                       "clear_first=true 时先全选删除原内容。",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "element_id": {"type": "string"},
                "clear_first": {"type": "boolean"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "press_keys",
        "description": "发送按键/快捷键序列（pywinauto 语法）：^ 表示 Ctrl，% 表示 Alt，+ 表示 Shift，"
                       "特殊键用花括号，如 {ENTER} {TAB} {ESC} {DELETE} {F2} {DOWN}；例：'^s'、'%f'、'{TAB 3}'。",
        "input_schema": {
            "type": "object",
            "properties": {"keys": {"type": "string"}},
            "required": ["keys"],
        },
    },
    {
        "name": "scroll",
        "description": "在截图坐标 (x, y) 处滚动鼠标滚轮；amount 为正向上、为负向下（单位：滚轮格数）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "amount": {"type": "integer"},
            },
            "required": ["x", "y", "amount"],
        },
    },
    {
        "name": "drag",
        "description": "按住鼠标左键从起点拖到终点再松开（拖放、移动、调整大小、滑块）。"
                       "起点用 from_element_id 或 from_x/from_y，终点用 to_element_id 或 to_x/to_y（截图像素）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_element_id": {"type": "string"},
                "from_x": {"type": "number"},
                "from_y": {"type": "number"},
                "to_element_id": {"type": "string"},
                "to_x": {"type": "number"},
                "to_y": {"type": "number"},
            },
        },
    },
    {
        "name": "set_value",
        "description": "通过 UI 自动化直接设置控件的值（ValuePattern）。键盘输入无效时的备选。",
        "input_schema": {
            "type": "object",
            "properties": {"element_id": {"type": "string"}, "value": {"type": "string"}},
            "required": ["element_id", "value"],
        },
    },
    {
        "name": "invoke",
        "description": "通过 UI 自动化触发控件的默认操作（依次尝试 调用/选中/切换/展开）。点击无效时的备选。",
        "input_schema": {
            "type": "object",
            "properties": {"element_id": {"type": "string"}},
            "required": ["element_id"],
        },
    },
    {
        "name": "wait",
        "description": "等待界面变化（最多 10 秒），然后返回新观察。",
        "input_schema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
    },
    {
        "name": "finish",
        "description": "结束任务并报告结果。completed：已从界面确认任务完成；failed：尝试后未能完成；"
                       "blocked：因软件或环境原因无法继续。问答类任务把答案写在 answer。",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": list(FINISH_STATUSES)},
                "answer": {"type": "string", "description": "问答类任务的答案；其他任务可留空"},
                "summary": {"type": "string", "description": "做了什么、依据界面上的什么确认了结果"},
            },
            "required": ["status", "summary"],
        },
    },
]

SYSTEM_PROMPT = """你是 Windows 桌面软件的测试执行员。你通过工具操作一个被测软件，完成用户给出的任务。

观察：每次动作后你会收到最新观察——窗口列表、控件列表（格式 `[eN] 类型 "名称" (状态) @(x,y)`，坐标为截图像素）和截图（可交互控件画了编号框，框上数字 N 对应 eN）。只以最新观察为准；控件编号每次观察都会重新分配，旧编号失效。

操作原则：
- 优先用 element_id 操作；控件列表里没有的目标，再用截图坐标。
- 每次动作后核对观察，确认动作确实生效再进行下一步。同一个动作没有效果时，不要重复超过 2 次，换一种方式（键盘快捷键、菜单、双击、右键菜单、invoke、set_value）。
- 只操作被测软件，不要关闭或退出它。
- 修改类任务：按软件的常规方式让修改真正生效（例如确认对话框、应用/确定、保存），并在界面上确认。
- 动作被框架拒绝（Refused）表示目标不在被测软件窗口内或软件不在前台，换一个目标或先处理弹出的窗口。

结束：完成或无法继续时调用 finish。只有在界面上确认任务已完成时才报告 completed；问答类任务把答案写在 answer，答案必须来自界面上实际看到的内容，不要猜测或编造。

预算：最多 {max_actions} 个动作、{max_minutes} 分钟。预算用尽后框架会停止你。"""


class Desktop(Protocol):
    def call(self, op: str, timeout: float | None = None, **args): ...


class ToolInputError(ValueError):
    pass


def _require_str(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ToolInputError(f"{key} 必须是非空字符串")
    return value


def _number(args: dict, key: str) -> float:
    value = args.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolInputError(f"{key} 必须是数字")
    return float(value)


def to_service_call(name: str, args: dict) -> tuple[str, dict]:
    """Validate a tool call and map it to a desktop-service op. Raises ToolInputError."""
    if not isinstance(args, dict):
        raise ToolInputError("参数必须是对象")
    if name == "click":
        button = args.get("button", "left")
        if button not in ("left", "right"):
            raise ToolInputError("button 只能是 left 或 right")
        double = bool(args.get("double", False))
        if args.get("element_id"):
            return "click_element", {"element_id": _require_str(args, "element_id"), "button": button, "double": double}
        if "x" in args and "y" in args:
            return "click_point", {"x": _number(args, "x"), "y": _number(args, "y"), "button": button, "double": double}
        raise ToolInputError("click 需要 element_id，或同时给出 x 和 y")
    if name == "type_text":
        text = args.get("text")
        if not isinstance(text, str) or text == "":
            raise ToolInputError("text 必须是非空字符串")
        out = {"text": text, "clear_first": bool(args.get("clear_first", False))}
        if args.get("element_id"):
            out["element_id"] = _require_str(args, "element_id")
        return "type_text", out
    if name == "press_keys":
        return "press_keys", {"keys": _require_str(args, "keys")}
    if name == "scroll":
        amount = args.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0:
            raise ToolInputError("amount 必须是非零整数")
        return "scroll", {"x": _number(args, "x"), "y": _number(args, "y"), "amount": max(-20, min(20, amount))}
    if name == "drag":
        out = {}
        for end in ("from", "to"):
            if args.get(f"{end}_element_id"):
                out[f"{end}_element_id"] = _require_str(args, f"{end}_element_id")
            elif f"{end}_x" in args and f"{end}_y" in args:
                out[f"{end}_x"] = _number(args, f"{end}_x")
                out[f"{end}_y"] = _number(args, f"{end}_y")
            else:
                raise ToolInputError(f"drag 需要 {end}_element_id，或同时给出 {end}_x 和 {end}_y")
        return "drag", out
    if name == "set_value":
        value = args.get("value")
        if not isinstance(value, str):
            raise ToolInputError("value 必须是字符串")
        return "set_value", {"element_id": _require_str(args, "element_id"), "value": value}
    if name == "invoke":
        return "invoke", {"element_id": _require_str(args, "element_id")}
    if name == "wait":
        return "wait", {"seconds": max(0.0, min(_number(args, "seconds"), 10.0))}
    raise ToolInputError(f"未知工具 {name}")


def parse_finish(args: dict) -> dict:
    status = args.get("status")
    if status not in FINISH_STATUSES:
        raise ToolInputError(f"status 必须是 {'/'.join(FINISH_STATUSES)} 之一")
    summary = args.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ToolInputError("summary 必须是非空字符串")
    answer = args.get("answer") or ""
    if not isinstance(answer, str):
        raise ToolInputError("answer 必须是字符串")
    return {"status": status, "answer": answer, "summary": summary}


@dataclass
class Budget:
    max_actions: int = 30
    max_seconds: float = 480.0
    max_model_calls: int = 45
    actions: int = 0
    model_calls: int = 0
    started: float = field(default_factory=time.monotonic)

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def exhausted(self) -> str | None:
        if self.actions >= self.max_actions:
            return "actions"
        if self.elapsed() >= self.max_seconds:
            return "time"
        if self.model_calls >= self.max_model_calls:
            return "model_calls"
        return None


@dataclass
class RunResult:
    outcome: str  # completed|failed|blocked (self-report) or no_finish|budget_<kind>|refusal|error
    answer: str = ""
    summary: str = ""
    actions: int = 0
    model_calls: int = 0
    seconds: float = 0.0
    tool_errors: int = 0
    refused: int = 0
    timeouts: int = 0
    usage: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class StepLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, kind: str, **data) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **data}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _image_block(path: str) -> dict:
    data = base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


def _block_to_dict(block) -> dict:
    return block.model_dump(exclude_none=True) if hasattr(block, "model_dump") else dict(block)


class Agent:
    def __init__(self, model, desktop: Desktop, run_dir: str | Path, budget: Budget | None = None,
                 action_timeout: float = 30.0):
        self.model = model
        self.desktop = desktop
        self.run_dir = Path(run_dir)
        self.budget = budget or Budget()
        self.action_timeout = action_timeout
        self.log = StepLog(self.run_dir / "steps.jsonl")
        self.counters = {"tool_errors": 0, "refused": 0, "timeouts": 0}

    def _observation_content(self) -> list[dict]:
        try:
            obs = self.desktop.call("observe", timeout=self.action_timeout)
        except (ServiceError, ToolTimeout) as exc:
            self.log.write("observe_error", error=str(exc))
            return [{"type": "text", "text": f"观察失败：{exc}"}]
        text = format_observation(obs)
        self.log.write("observe", annotated=obs["annotated"], screenshot=obs["screenshot"],
                       elements=len(obs["elements"]), windows=[w["title"] for w in obs["windows"]])
        return [{"type": "text", "text": text}, _image_block(obs["annotated"])]

    def _execute(self, name: str, args: dict) -> tuple[str, bool]:
        """Run one action tool. Returns (message, is_error)."""
        try:
            op, call_args = to_service_call(name, args)
        except ToolInputError as exc:
            self.counters["tool_errors"] += 1
            return f"参数错误：{exc}", True
        self.budget.actions += 1
        started = time.monotonic()
        try:
            result = self.desktop.call(op, timeout=self.action_timeout, **call_args)
            self.log.write("action", tool=name, op=op, args=call_args, result=result,
                           seconds=round(time.monotonic() - started, 2))
            return f"{name} 已执行。", False
        except ToolTimeout as exc:
            self.counters["timeouts"] += 1
            self.log.write("action", tool=name, op=op, args=call_args, error=str(exc))
            return f"执行超时：{exc}", True
        except ServiceError as exc:
            if exc.kind == "Refused":
                self.counters["refused"] += 1
            else:
                self.counters["tool_errors"] += 1
            self.log.write("action", tool=name, op=op, args=call_args, error=str(exc))
            return f"执行失败（{exc.kind}）：{exc.message}", True

    def _result(self, outcome: str, **extra) -> RunResult:
        res = RunResult(outcome=outcome, actions=self.budget.actions, model_calls=self.budget.model_calls,
                        seconds=round(self.budget.elapsed(), 1),
                        usage=self.model.usage.to_dict(getattr(self.model, "model", None)),
                        **self.counters, **extra)
        self.log.write("result", **res.to_dict())
        return res

    def run(self, task: str) -> RunResult:
        system = SYSTEM_PROMPT.format(max_actions=self.budget.max_actions,
                                      max_minutes=round(self.budget.max_seconds / 60, 1))
        self.log.write("start", task=task, model=getattr(self.model, "model", None),
                       effort=getattr(self.model, "effort", None), budget=asdict(self.budget))
        messages: list[dict] = [{"role": "user", "content": [
            {"type": "text", "text": f"任务：{task}\n\n当前观察："}, *self._observation_content()]}]
        nudged = False
        final_call = False  # budget exhausted: one last model call that may only finish

        while True:
            if self.budget.model_calls >= self.budget.max_model_calls:
                return self._result("budget_model_calls")
            if self.budget.elapsed() >= self.budget.max_seconds + 60:
                return self._result("budget_time")
            self.budget.model_calls += 1
            try:
                response = self.model.create(system, messages, TOOLS)
            except Exception as exc:  # API errors after SDK retries
                self.log.write("model_error", error=f"{type(exc).__name__}: {exc}")
                return self._result("error", error=f"{type(exc).__name__}: {exc}")
            content = [_block_to_dict(b) for b in response.content]
            self.log.write("model", stop_reason=response.stop_reason,
                           text=[b.get("text") for b in content if b.get("type") == "text"],
                           tool_calls=[{"name": b["name"], "input": b["input"]} for b in content
                                       if b.get("type") == "tool_use"],
                           usage=_block_to_dict(response.usage))
            messages.append({"role": "assistant", "content": content})

            if response.stop_reason == "refusal":
                return self._result("refusal")
            tool_uses = [b for b in content if b.get("type") == "tool_use"]

            if final_call:  # last chance after budget exhaustion: only a valid finish counts
                for block in tool_uses:
                    if block["name"] == "finish":
                        try:
                            fin = parse_finish(block.get("input") or {})
                            return self._result(fin["status"], answer=fin["answer"], summary=fin["summary"],
                                                error=f"budget_{final_call}")
                        except ToolInputError:
                            break
                return self._result(f"budget_{final_call}")

            if not tool_uses:
                if response.stop_reason == "max_tokens":
                    messages.append({"role": "user", "content": "输出被截断，请继续，用工具推进任务。"})
                    continue
                if nudged:
                    return self._result("no_finish")
                nudged = True
                messages.append({"role": "user", "content": "请通过工具继续操作；任务结束时必须调用 finish 报告结果。"})
                continue

            results: list[dict] = []
            acted = False
            skip_reason = ""
            for block in tool_uses:
                name, args = block["name"], block.get("input") or {}
                if name == "finish":
                    if acted:  # finish in the same turn as actions: report only after seeing their effect
                        msg, is_error = "未接受：本轮有动作，请先查看动作后的观察再调用 finish。", True
                    else:
                        try:
                            fin = parse_finish(args)
                            return self._result(fin["status"], answer=fin["answer"], summary=fin["summary"])
                        except ToolInputError as exc:
                            msg, is_error = f"参数错误：{exc}", True
                elif skip_reason:
                    msg, is_error = skip_reason, True
                elif self.budget.exhausted():
                    msg, is_error = "未执行：预算已用尽。", True
                else:
                    msg, is_error = self._execute(name, args)
                    acted = True
                    if is_error:
                        skip_reason = "未执行：本轮前一个动作失败，请先查看最新观察。"
                results.append({"type": "tool_result", "tool_use_id": block["id"],
                                "content": [{"type": "text", "text": msg}], "is_error": is_error})

            if acted:
                results[-1]["content"].extend(self._observation_content())
            kind = self.budget.exhausted()
            if kind:
                final_call = kind
                results[-1]["content"].append({"type": "text", "text":
                    f"预算已用尽（{kind}），不能再执行动作。请立即调用 finish 报告结果。"})
            messages.append({"role": "user", "content": results})
