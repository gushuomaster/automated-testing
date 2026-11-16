"""M1 autonomous exploration: plan charters from the manual, run each as an independent agent session, summarize.

The framework enforces validity and budgets; the model only proposes charters and drives the GUI.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .agent import Agent, Budget
from .defects import DEFECT_TOOL, NOTE_TOOL, Findings, make_handlers
from .model import Usage

MIN_CHARTERS = 4
MAX_CHARTERS = 6
MIN_CHARTER_ACTIONS = 10
MAX_CHARTER_ACTIONS = 80
MANUAL_GLOB = "*.adoc"

CHARTER_TOOL = {
    "name": "submit_charters",
    "description": "提交测试章程。每个章程是一次独立的 GUI 探索会话：一个功能区 + 关注点 + 动作预算。",
    "input_schema": {
        "type": "object",
        "properties": {
            "charters": {
                "type": "array",
                "description": f"{MIN_CHARTERS} 到 {MAX_CHARTERS} 个章程",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "唯一编号，如 C1"},
                        "title": {"type": "string"},
                        "area": {"type": "string", "description": "被测功能区，如 条目编辑"},
                        "focus": {"type": "string", "description": "关注点：要核对手册里的哪些行为"},
                        "manual_refs": {"type": "array", "items": {"type": "string"},
                                        "description": "相关的手册章节标题"},
                        "max_actions": {"type": "integer"},
                    },
                    "required": ["id", "title", "area", "focus", "manual_refs", "max_actions"],
                },
            },
        },
        "required": ["charters"],
    },
}

PLAN_SYSTEM = (
    "你是软件测试负责人。根据给出的用户手册节选，为 KeePassXC 桌面版规划探索式测试章程。"
    "章程之间的功能区应尽量不重叠，并覆盖手册里描述的主要界面和操作。"
    "只依据手册内容规划，调用 submit_charters 提交结果。"
)


class PlanError(ValueError):
    pass


@dataclass
class Charter:
    id: str
    title: str
    area: str
    focus: str
    manual_refs: list
    max_actions: int

    def to_dict(self) -> dict:
        return asdict(self)


def _str(item: dict, key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{where}: {key} 必须是非空字符串")
    return value.strip()


def parse_charters(args: dict) -> list[Charter]:
    """Validate a submit_charters call. Raises PlanError; there is no default plan to fall back on."""
    items = args.get("charters") if isinstance(args, dict) else None
    if not isinstance(items, list) or not (MIN_CHARTERS <= len(items) <= MAX_CHARTERS):
        raise PlanError(f"charters 必须是 {MIN_CHARTERS} 到 {MAX_CHARTERS} 个章程的列表")
    out: list[Charter] = []
    for i, item in enumerate(items, 1):
        where = f"章程 {i}"
        if not isinstance(item, dict):
            raise PlanError(f"{where}: 必须是对象")
        cid = _str(item, "id", where)
        if any(c.id == cid for c in out):
            raise PlanError(f"{where}: 编号 {cid} 重复")
        refs = item.get("manual_refs")
        if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or not r.strip() for r in refs):
            raise PlanError(f"{where}: manual_refs 必须是非空字符串列表")
        actions = item.get("max_actions")
        if isinstance(actions, bool) or not isinstance(actions, int) \
                or not (MIN_CHARTER_ACTIONS <= actions <= MAX_CHARTER_ACTIONS):
            raise PlanError(f"{where}: max_actions 必须是 {MIN_CHARTER_ACTIONS} 到 {MAX_CHARTER_ACTIONS} 的整数")
        out.append(Charter(id=cid, title=_str(item, "title", where), area=_str(item, "area", where),
                           focus=_str(item, "focus", where), manual_refs=[r.strip() for r in refs],
                           max_actions=actions))
    return out


def load_manual(manual_dir: Path) -> str:
    files = sorted(Path(manual_dir).glob(MANUAL_GLOB))
    if not files:
        raise PlanError(f"手册目录里没有 {MANUAL_GLOB}：{manual_dir}")
    return "\n\n".join(f"=== {f.name} ===\n{f.read_text(encoding='utf-8')}" for f in files)


PLAN_ATTEMPTS = 3


def plan_charters(model, manual_text: str, goal: str, attempts: int = PLAN_ATTEMPTS,
                  log: list | None = None) -> list[Charter]:
    """Model calls without GUI. The model must answer with a valid submit_charters call. With thinking on the
    API cannot force the tool, so a miss is fed back (validation error as tool_result, or a reminder to call
    the tool) and retried, at most `attempts` calls. There is never a default plan. Each failed attempt is
    appended to `log`; if all fail, PlanError carries the last reason."""
    messages = [{"role": "user", "content": f"测试目标：{goal}\n\n用户手册节选：\n{manual_text}"}]
    reason = ""
    for attempt in range(1, attempts + 1):
        response = model.create(PLAN_SYSTEM, messages, [CHARTER_TOOL])
        blocks = [b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else dict(b)
                  for b in response.content]
        call = next((b for b in blocks if b.get("type") == "tool_use" and b.get("name") == "submit_charters"), None)
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if call is not None:
            try:
                return parse_charters(call.get("input") or {})
            except PlanError as exc:
                # Keep what the model actually sent (and why it stopped) so a bad plan can be diagnosed.
                raw = json.dumps(call.get("input"), ensure_ascii=False, default=str)[:800]
                reason = f"{exc}（stop_reason={response.stop_reason}；收到：{raw}）"
                feedback = [{"type": "tool_result", "tool_use_id": call["id"], "is_error": True,
                             "content": f"章程不合格：{exc}。请修正后重新调用 submit_charters。"}]
        else:
            reason = f"模型没有调用 submit_charters（stop_reason={response.stop_reason}；文字：{text[:300]}）"
            feedback = [{"type": "text", "text": "请调用 submit_charters 工具提交章程，不要只用文字回答。"}]
        if log is not None:
            log.append({"attempt": attempt, "error": reason})
        messages += [{"role": "assistant", "content": blocks}, {"role": "user", "content": feedback}]
    raise PlanError(f"{attempts} 次尝试都没有得到合格章程，最后一次：{reason}")


# ---- charter execution ---------------------------------------------------------------------

DEFAULT_CHARTER_LIMITS = {"max_seconds": 480.0, "max_model_calls": 60, "max_wall_seconds": 1500.0}


@dataclass
class TotalBudget:
    """Whole-run limits across all charters; enforced by the framework before each charter starts."""

    max_actions: int = 300
    max_model_calls: int = 400
    max_wall_seconds: float = 7200.0
    actions: int = 0
    model_calls: int = 0
    started: float = field(default_factory=time.monotonic)

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def exhausted(self) -> str | None:
        if self.actions >= self.max_actions:
            return "actions"
        if self.model_calls >= self.max_model_calls:
            return "model_calls"
        if self.elapsed() >= self.max_wall_seconds:
            return "wall"
        return None

    def charter_budget(self, charter: Charter, limits: dict) -> dict:
        """Per-charter Budget arguments, capped by what is left of the total."""
        return {
            "max_actions": min(charter.max_actions, self.max_actions - self.actions),
            "max_seconds": limits["max_seconds"],
            "max_model_calls": min(limits["max_model_calls"], self.max_model_calls - self.model_calls),
            "max_wall_seconds": min(limits["max_wall_seconds"], self.max_wall_seconds - self.elapsed()),
        }


def charter_task(goal: str, charter: Charter, notes: str, manual_text: str) -> str:
    parts = [
        f"测试目标：{goal}",
        f"本次章程 {charter.id}《{charter.title}》\n功能区：{charter.area}\n关注点：{charter.focus}\n"
        f"相关手册章节：{'、'.join(charter.manual_refs)}",
    ]
    if notes:
        parts.append("前序章程记录的界面笔记（只是界面信息，不是缺陷结论）：\n" + notes)
    parts.append("用户手册节选（判断期望行为的依据）：\n" + manual_text)
    return "\n\n".join(parts)


def run_charter(model, charter: Charter, task: str, charter_dir: Path, session, budget_args: dict,
                findings: Findings, system_prompt: str | None) -> dict:
    """One independent agent session. `session(charter, charter_dir)` is a context manager that resets and
    launches the app, yields a desktop already targeted at it, and closes the app on exit."""
    model.usage = Usage()
    notes_before, reports_before = len(findings.notes), len(findings.reports)
    record = {"id": charter.id, "title": charter.title, "status": "done", "budget": budget_args}
    result = None
    try:
        with session(charter, charter_dir) as desktop:
            agent = Agent(model, desktop, charter_dir, budget=Budget(**budget_args), system_prompt=system_prompt,
                          extra_tools=[NOTE_TOOL, DEFECT_TOOL], handlers=make_handlers(findings, charter.id))
            try:
                result = agent.run(task)
            except Exception as exc:  # harness bug: record and keep going
                traceback.print_exc()
                result = agent._result("harness_error", error=f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # session setup or teardown failed
        traceback.print_exc()
        record.update(status="error", error=f"{type(exc).__name__}: {exc}")
    if result is not None:
        record["run"] = result.to_dict()
        record["outcome"] = result.outcome
    record["notes"] = len(findings.notes) - notes_before
    record["reports"] = len(findings.reports) - reports_before
    return record


def run_exploration(model, charters: list[Charter], goal: str, manual_text: str, out_dir: Path, session,
                    findings: Findings | None = None, total: TotalBudget | None = None,
                    charter_limits: dict | None = None, system_prompt: str | None = None):
    """Run charters in order, each in a fresh agent context carrying earlier notes (never earlier reports).

    Once the total budget is exhausted the remaining charters are recorded as skipped_budget.
    Returns (records, findings)."""
    findings = findings or Findings()
    total = total or TotalBudget()
    limits = {**DEFAULT_CHARTER_LIMITS, **(charter_limits or {})}
    out_dir = Path(out_dir)
    records = []
    for index, charter in enumerate(charters, 1):
        charter_dir = out_dir / f"charter-{index}"
        charter_dir.mkdir(parents=True, exist_ok=True)
        reason = total.exhausted()
        if reason:
            record = {"id": charter.id, "title": charter.title, "status": "skipped_budget", "reason": reason}
        else:
            task = charter_task(goal, charter, findings.notes_for_prompt(), manual_text)
            record = run_charter(model, charter, task, charter_dir, session, total.charter_budget(charter, limits),
                                 findings, system_prompt)
            run = record.get("run") or {}
            total.actions += run.get("actions", 0)
            total.model_calls += run.get("model_calls", 0)
        (charter_dir / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str),
                                                 encoding="utf-8")
        records.append(record)
    return records, findings


# ---- summary: duplicate grouping ---------------------------------------------------------------

DEDUP_SYSTEM = (
    "你是缺陷报告评审。判断哪些报告描述的是同一个缺陷（同一现象、同一功能点），只做分组，不判断是否真实缺陷。"
    "只输出一个 JSON 对象，不要输出其他内容：{\"groups\": [[\"D001\", \"D003\"], [\"D002\"]]}。"
    "每个报告编号必须恰好出现在一个分组里。"
)


class DedupError(ValueError):
    pass


def parse_groups(text: str, ids: list[str]) -> list[list[str]]:
    """Parse the model's grouping; every report id must appear exactly once. Raises DedupError."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise DedupError("回复里没有 JSON 对象")
    try:
        groups = json.loads(text[start:end + 1]).get("groups")
    except (ValueError, AttributeError) as exc:
        raise DedupError(f"JSON 无法解析：{exc}")
    if not isinstance(groups, list) or any(
            not isinstance(g, list) or not g or any(not isinstance(i, str) for i in g) for g in groups):
        raise DedupError("groups 必须是非空字符串列表的列表")
    flat = [i for g in groups for i in g]
    if sorted(flat) != sorted(ids):
        raise DedupError("分组没有让每个报告编号恰好出现一次")
    return [sorted(g) for g in sorted(groups, key=lambda g: min(g))]


def _as_result(groups: list[list[str]], undeduped: bool, error: str = "") -> dict:
    out = {"undeduped": undeduped, "groups": [{"keep": g[0], "merged": g[1:]} for g in groups]}
    if error:
        out["error"] = error
    return out


def dedupe_reports(model, reports: list) -> dict:
    """One tool-less model call that groups duplicate reports. The first report of a group is kept and the
    others are listed as merged (their evidence stays in reports.json). On any failure every report is kept
    and the result is marked undeduped."""
    ids = [r.id for r in reports]
    if len(reports) < 2:
        return _as_result([[i] for i in ids], False)
    brief = [{k: v for k, v in r.to_dict().items() if k != "evidence"} for r in reports]
    prompt = "缺陷报告列表：\n" + json.dumps(brief, ensure_ascii=False, indent=1)
    try:
        response = model.create(DEDUP_SYSTEM, [{"role": "user", "content": prompt}], [])
        text = "".join(
            (b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else dict(b)).get("text", "")
            for b in response.content)
        return _as_result(parse_groups(text, ids), False)
    except Exception as exc:
        return _as_result([[i] for i in ids], True, f"{type(exc).__name__}: {exc}")


# ---- scoring: human judgements against ground truth ----------------------------------------------

LABELS = ('known', 'new', 'not_defect', 'undetermined')
REPRO_STATUSES = ('confirmed', 'excluded', 'pending')
TOKEN_KEYS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')


class ScoreError(ValueError):
    pass


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def check_judgements(judgement: dict, kept: list, defects: dict) -> dict:
    '''Validate the human judgement file; returns {report_id: judgement}. Raises ScoreError.'''
    allowed = '/'.join(LABELS)
    out: dict = {}
    for j in (judgement or {}).get('judgements', []):
        rid = j.get('report_id')
        if rid not in kept:
            raise ScoreError(f'判定指向的报告不在去重后的报告里：{rid}')
        if rid in out:
            raise ScoreError(f'报告 {rid} 被重复判定')
        if j.get('label') not in LABELS:
            raise ScoreError(f'报告 {rid} 的 label 必须是 {allowed} 之一')
        if not str(j.get('basis') or '').strip():
            raise ScoreError(f'报告 {rid} 缺少判定依据 basis')
        if j['label'] == 'known' and j.get('truth_id') not in defects:
            raise ScoreError(f'报告 {rid} 判为 known，但 truth_id 不在 truth.json 里')
        out[rid] = j
    return out


def coverage_of(plan: list, records: list) -> dict:
    status_count = {s: sum(1 for r in records if r.get('status') == s) for s in ('done', 'skipped_budget', 'error')}
    done_ids = {r['id'] for r in records if r.get('status') == 'done'}
    refs = sorted({ref for c in plan if c['id'] in done_ids for ref in c['manual_refs']})
    return {'charters_total': len(plan), **status_count, 'manual_refs_covered': refs}


def cost_of(records: list, overhead: list = ()) -> dict:
    '''Actions, time and tokens over all charter runs, plus overhead usage (planning, dedupe calls).'''
    runs = [r['run'] for r in records if r.get('run')]
    usage = [run.get('usage') or {} for run in runs] + [u for u in overhead if u]
    costs = [u['estimated_cost_usd'] for u in usage if u.get('estimated_cost_usd') is not None]
    return {
        'actions': sum(run.get('actions', 0) for run in runs),
        'model_calls': sum(u.get('calls', 0) for u in overhead if u) + sum(run.get('model_calls', 0) for run in runs),
        'seconds': round(sum(run.get('seconds', 0) for run in runs), 1),
        **{k: sum(u.get(k, 0) for u in usage) for k in TOKEN_KEYS},
        'estimated_cost_usd': round(sum(costs), 4) if costs else None,
    }


def score_exploration(reports_doc: dict, truth: dict, judgement: dict, plan: list, records: list,
                      overhead: list = ()) -> dict:
    '''Recall, precision, coverage and cost. Labels come only from the human judgement file. Unjudged and
    undetermined reports are listed apart and count in neither numerator nor denominator of precision;
    only repro_status=confirmed defects count for recall.'''
    kept = [g['keep'] for g in reports_doc['dedupe']['groups']]
    defects: dict = {}
    for d in truth['defects']:
        if d.get('repro_status') not in REPRO_STATUSES:
            raise ScoreError('truth.json 里 ' + str(d.get('id')) + ' 的 repro_status 非法')
        defects[d['id']] = d
    judged = check_judgements(judgement, kept, defects)
    counts = {label: sum(1 for j in judged.values() if j['label'] == label) for label in LABELS}
    real = counts['known'] + counts['new']
    confirmed = sorted(i for i, d in defects.items() if d['repro_status'] == 'confirmed')
    hit = {j['truth_id'] for j in judged.values() if j['label'] == 'known'}
    found = sorted(hit & set(confirmed))
    return {
        'reports': {'total': len(reports_doc['reports']), 'after_dedupe': len(kept),
                    'undeduped': bool(reports_doc['dedupe'].get('undeduped')), 'counts': counts,
                    'unjudged': [i for i in kept if i not in judged]},
        'precision': _ratio(real, real + counts['not_defect']),
        'recall': {'found': found, 'missed': sorted(set(confirmed) - set(found)),
                   'confirmed_total': len(confirmed), 'value': _ratio(len(found), len(confirmed))},
        'coverage': coverage_of(plan, records),
        'cost': cost_of(records, overhead),
    }


def _read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def score_run(run_dir: Path, truth_path: Path, judgement_path: Path | None = None) -> dict:
    '''Score one run directory (plan.json, reports.json, charter-N/result.json). A missing judgement file
    means nothing has been judged yet: every kept report is listed as unjudged.'''
    run_dir = Path(run_dir)
    results = sorted(run_dir.glob('charter-*/result.json'), key=lambda p: int(p.parent.name.split('-')[1]))
    judgement = _read_json(judgement_path) if judgement_path and Path(judgement_path).exists() else {}
    plan_doc, reports_doc = _read_json(run_dir / 'plan.json'), _read_json(run_dir / 'reports.json')
    return score_exploration(reports_doc, _read_json(truth_path), judgement, plan_doc['charters'],
                             [_read_json(p) for p in results],
                             overhead=[plan_doc.get('usage') or {}, reports_doc.get('usage') or {}])


# ---- exploration system prompt ------------------------------------------------------------------

EXPLORE_SYSTEM_PROMPT = """你是 Windows 桌面软件的探索式测试员。你通过工具操作被测软件，按给定的章程探索功能，对照用户手册和通用软件准则，发现并报告缺陷。

观察：每次动作后你会收到最新观察——窗口列表、控件列表（格式 `[eN] 类型 "名称" (状态) @(x,y)`，坐标为截图像素）和截图（可交互控件画了编号框，框上数字 N 对应 eN）。只以最新观察为准；控件编号每次观察都会重新分配，旧编号失效。

探索原则：
- 围绕章程的功能区和关注点，逐项核对手册描述的行为，也留意手册没写但按通用软件常识应当成立的行为。
- 用 note 记录界面和功能发现（控件位置、菜单结构、行为），供后续章程参考。note 不是缺陷报告。
- 怀疑有缺陷时，先回到干净状态重现一次，排除自己的操作失误，再核对手册。只依据手册或通用软件准则判断，不要猜测。
- 软件行为与手册或通用准则不一致才算缺陷。自己点错、对话框没处理、动作没有生效，都不是缺陷。
- report_defect 的证据是最新一次观察的截图：在看到异常出现的那次观察之后、并且本轮没有其他动作时调用。
- 动作被框架拒绝（Refused）表示目标不在被测软件窗口内或软件不在前台，换一个目标或先处理弹出的窗口。
- 同一个动作没有效果时，不要重复超过 2 次，换一种方式。
- 只操作被测软件，不要关闭或退出它。

结束：章程探索完或无法继续时调用 finish。completed 表示章程范围已探索完；failed 表示尝试后未能完成；blocked 表示因软件或环境原因无法继续。summary 写清探索了什么、发现了什么。

预算：最多 {max_actions} 个动作、{max_minutes} 分钟。预算用尽后框架会停止你。"""


# ---- whole run: plan -> charters -> dedupe -> outputs ------------------------------------------------

def default_goal(password: str) -> str:
    return (f"对 KeePassXC 桌面版做探索式测试，找出与用户手册或通用软件准则不一致的行为。"
            f"软件启动后停在数据库解锁界面，数据库主密码是 {password}。")


def _write_json(path: Path, data) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _usage_dict(model) -> dict:
    usage = getattr(model, 'usage', None)
    return usage.to_dict(getattr(model, 'model', None)) if isinstance(usage, Usage) else {}


def render_report(plan: list, records: list, reports: list, dedupe: dict, out_dir: Path) -> str:
    '''Human-readable report: charters, then each kept defect with the reports merged into it.'''
    by_id = {r.id: r for r in reports}
    lines = ['# M1 自主探索报告', '', '## 章程', '', '| 编号 | 标题 | 状态 | 结果 | 动作 | 报告 |', '|---|---|---|---|---|---|']
    for rec in records:
        run = rec.get('run') or {}
        lines.append(f"| {rec['id']} | {rec['title']} | {rec['status']} | {rec.get('outcome', '')} "
                     f"| {run.get('actions', '')} | {rec.get('reports', '')} |")
    groups = dedupe['groups']
    lines += ['', f'## 缺陷报告（{len(reports)} 条，去重后 {len(groups)} 条'
              + ('，去重失败未合并' if dedupe.get('undeduped') else '') + '）', '']
    if not groups:
        lines.append('没有报告缺陷。')
    for g in groups:
        r = by_id[g['keep']]
        lines += [f"### {r.id} {r.title}", '',
                  f"- 章程：{r.charter}　严重度：{r.severity}　期望依据：{r.expected_source}",
                  f"- 期望：{r.expected}", f"- 实际：{r.actual}", '- 复现步骤：']
        lines += [f"  {i}. {s}" for i, s in enumerate(r.steps, 1)]
        for rid in [r.id] + g['merged']:
            shot = by_id[rid].evidence.get('annotated', '')
            rel = Path(shot).relative_to(out_dir).as_posix() if shot and Path(shot).is_relative_to(out_dir) else shot
            lines.append(f"- 证据（{rid}）：{rel}")
        if g['merged']:
            lines.append(f"- 合并的重复报告：{'、'.join(g['merged'])}")
        lines.append('')
    refs = coverage_of(plan, records)['manual_refs_covered']
    lines += ['## 覆盖的手册章节', '', '、'.join(refs) if refs else '无', '']
    return '\n'.join(lines)


def explore_run(model, manual_text: str, goal: str, out_dir: Path, session, total: TotalBudget | None = None,
                charter_limits: dict | None = None) -> dict:
    '''Plan, run every charter, dedupe and write all outputs to out_dir. Returns the summary.

    Outputs: plan.json, charter-N/..., notes.json, reports.json, report.md, summary.json.'''
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.usage = Usage()
    plan_failures: list = []
    try:
        charters = plan_charters(model, manual_text, goal, log=plan_failures)
    except PlanError:
        _write_json(out_dir / 'plan-failed.json', {'goal': goal, 'failures': plan_failures,
                                                   'usage': _usage_dict(model)})
        raise
    plan = [c.to_dict() for c in charters]
    plan_usage = _usage_dict(model)
    _write_json(out_dir / 'plan.json', {'goal': goal, 'charters': plan, 'usage': plan_usage,
                                        'failed_attempts': plan_failures})

    records, findings = run_exploration(model, charters, goal, manual_text, out_dir, session, total=total,
                                        charter_limits=charter_limits, system_prompt=EXPLORE_SYSTEM_PROMPT)
    _write_json(out_dir / 'notes.json', findings.notes)

    model.usage = Usage()
    dedupe = dedupe_reports(model, findings.reports)
    dedupe_usage = _usage_dict(model)
    _write_json(out_dir / 'reports.json', {'reports': [r.to_dict() for r in findings.reports], 'dedupe': dedupe,
                                           'usage': dedupe_usage})
    (out_dir / 'report.md').write_text(render_report(plan, records, findings.reports, dedupe, out_dir),
                                       encoding='utf-8')
    summary = {
        'model': getattr(model, 'model', None),
        'effort': getattr(model, 'effort', None),
        'reports': {'total': len(findings.reports), 'after_dedupe': len(dedupe['groups']),
                    'undeduped': dedupe['undeduped']},
        'notes': len(findings.notes),
        'coverage': coverage_of(plan, records),
        'cost': cost_of(records, [plan_usage, dedupe_usage]),
        'per_charter': [{k: r.get(k) for k in ('id', 'status', 'outcome', 'reports', 'notes', 'error')}
                        | {'actions': (r.get('run') or {}).get('actions')} for r in records],
    }
    _write_json(out_dir / 'summary.json', summary)
    return summary


def keepassxc_session(app_dir: Path, seed: Path, password: str):
    '''Real session factory: reset config and database copy, launch, target the desktop service, close.'''
    from contextlib import contextmanager

    from .apps.keepassxc import KeePassXCEnv
    from .desktop.client import DesktopClient

    @contextmanager
    def session(charter: Charter, charter_dir: Path):
        env = KeePassXCEnv(app_dir=app_dir, seed_db=seed, password=password, run_dir=Path(charter_dir) / 'data')
        env.reset()
        try:
            pid = env.launch()
            with DesktopClient(Path(charter_dir) / 'shots') as desktop:
                desktop.call('set_target', pids=[pid])
                yield desktop
        finally:
            _write_json(Path(charter_dir) / 'stop.json', env.stop())

    return session


def remote_session(host: str, port: int, token: str, seed: str, password: str):
    '''Session factory for the VM guest: the fixed kpxc_* ops reset, launch and stop the app inside the guest.'''
    from contextlib import contextmanager

    from .desktop.remote_client import RemoteDesktopClient

    @contextmanager
    def session(charter: Charter, charter_dir: Path):
        with RemoteDesktopClient(host, port, token, Path(charter_dir) / 'shots') as desktop:
            try:
                desktop.call('kpxc_reset', timeout=60, seed=seed, password=password)
                pid = desktop.call('kpxc_launch', timeout=60)['pid']
                desktop.call('set_target', pids=[pid])
                yield desktop
            finally:
                try:
                    stop = desktop.call('kpxc_stop', timeout=60)
                except Exception as exc:
                    stop = {'error': f'{type(exc).__name__}: {exc}'}
                _write_json(Path(charter_dir) / 'stop.json', stop)

    return session


def main(argv=None) -> int:
    import argparse
    import os
    import sys
    from datetime import datetime

    repo = Path(__file__).resolve().parents[3]
    bench = repo / 'benchmarks' / 'keepassxc-m1'
    p = argparse.ArgumentParser(description='M1 autonomous exploration of KeePassXC (or --score a finished run). '
                                'Requires ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY; nobody may use the mouse or '
                                'keyboard while it runs.')
    p.add_argument('--manual-dir', type=Path, default=bench / 'manual')
    p.add_argument('--seed', type=Path, default=bench / 'seed.kdbx')
    p.add_argument('--password', default='Test@2026')
    p.add_argument('--app-dir', type=Path, default=Path(os.environ.get(
        'KPXC_APP_DIR', repo / 'artifacts/feasibility-01/downloads/kpxc-2.7.6/app/KeePassXC-2.7.6-Win64')))
    p.add_argument('--model', default='claude-opus-5-5')
    p.add_argument('--effort', default='medium', help="low|medium|high|xhigh|max or 'none' to omit")
    p.add_argument('--total-actions', type=int, default=300)
    p.add_argument('--total-model-calls', type=int, default=400)
    p.add_argument('--total-wall-seconds', type=float, default=7200)
    p.add_argument('--out', type=Path)
    p.add_argument('--remote', metavar='HOST:PORT', help='run inside the VM guest through its remote desktop service')
    p.add_argument('--token-file', type=Path, default=repo / 'artifacts' / 'vm' / 'token.txt')
    p.add_argument('--guest-seed', default='keepassxc-m1/seed.kdbx', help='seed path under the guest benchmarks dir')
    p.add_argument('--local', action='store_true', help='allow running on this machine desktop (not isolated)')
    p.add_argument('--score', type=Path, metavar='RUN_DIR', help='score a finished run instead of running')
    p.add_argument('--truth', type=Path, default=bench / 'truth.json')
    p.add_argument('--judgement', type=Path, help='default: RUN_DIR/judgement.json')
    args = p.parse_args(argv)

    if args.score:
        try:
            score = score_run(args.score, args.truth, args.judgement or args.score / 'judgement.json')
        except ScoreError as exc:
            print(f'评分失败：{exc}', file=sys.stderr)
            return 2
        _write_json(args.score / 'score.json', score)
        print(json.dumps(score, ensure_ascii=False, indent=2))
        return 0

    if not args.remote and not args.local:
        print('refusing to run on the host desktop: pass --remote HOST:PORT (VM guest) or --local', file=sys.stderr)
        return 2
    if not (os.environ.get('ANTHROPIC_AUTH_TOKEN') or os.environ.get('ANTHROPIC_API_KEY')):
        print('missing ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY', file=sys.stderr)
        return 2
    from .model import ClaudeModel

    out_dir = args.out or repo / 'artifacts' / 'm1-runs' / datetime.now().strftime('%Y%m%d-%H%M%S')
    model = ClaudeModel(model=args.model, effort=None if args.effort == 'none' else args.effort)
    total = TotalBudget(max_actions=args.total_actions, max_model_calls=args.total_model_calls,
                        max_wall_seconds=args.total_wall_seconds)
    if args.remote:
        host, _, port = args.remote.rpartition(':')
        token = args.token_file.read_text(encoding='utf-8').strip()
        session = remote_session(host, int(port), token, args.guest_seed, args.password)
    else:
        session = keepassxc_session(args.app_dir, args.seed, args.password)
    summary = explore_run(model, load_manual(args.manual_dir), default_goal(args.password), out_dir, session,
                          total=total)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'outputs: {out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
