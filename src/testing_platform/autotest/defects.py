'''Defect reports and notes recorded by the exploration agent. The framework, not the prompt, enforces validity and limits.'''

from __future__ import annotations

from dataclasses import asdict, dataclass

from .agent import ToolInputError

SEVERITIES = ('low', 'medium', 'high')
MAX_REPORTS_PER_CHARTER = 5
MAX_NOTES_PER_CHARTER = 40
MAX_NOTE_CHARS = 500
MAX_FIELD_CHARS = 2000
MAX_STEPS = 30


def _text(args: dict, key: str, limit: int = MAX_FIELD_CHARS) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f'{key} 必须是非空字符串')
    if len(value.strip()) > limit:
        raise ToolInputError(f'{key} 过长（上限 {limit} 字符）')
    return value.strip()


def parse_report_defect(args: dict) -> dict:
    '''Validate a report_defect call. Raises ToolInputError; nothing invalid is recorded.'''
    if not isinstance(args, dict):
        raise ToolInputError('参数必须是对象')
    steps = args.get('steps')
    if (not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS
            or any(not isinstance(s, str) or not s.strip() for s in steps)):
        raise ToolInputError(f'steps 必须是 1 到 {MAX_STEPS} 条非空字符串的列表')
    source = _text(args, 'expected_source')
    if source != 'general' and not (source.startswith('manual:') and source[len('manual:'):].strip()):
        raise ToolInputError('expected_source 必须是 general 或 manual:<手册章节>')
    severity = args.get('severity')
    if severity not in SEVERITIES:
        allowed = '/'.join(SEVERITIES)
        raise ToolInputError(f'severity 必须是 {allowed} 之一')
    return {
        'title': _text(args, 'title', 200),
        'steps': [s.strip() for s in steps],
        'expected': _text(args, 'expected'),
        'expected_source': source,
        'actual': _text(args, 'actual'),
        'severity': severity,
    }


def parse_note(args: dict) -> str:
    if not isinstance(args, dict):
        raise ToolInputError('参数必须是对象')
    return _text(args, 'text', MAX_NOTE_CHARS)


@dataclass
class DefectReport:
    id: str
    charter: str
    title: str
    steps: list
    expected: str
    expected_source: str
    actual: str
    severity: str
    evidence: dict  # screenshot / annotated paths of the observation current when reported

    def to_dict(self) -> dict:
        return asdict(self)


class Findings:
    '''Notes and defect reports collected across charters.'''

    def __init__(self) -> None:
        self.notes: list[dict] = []
        self.reports: list[DefectReport] = []

    def add_note(self, charter: str, args: dict) -> dict:
        text = parse_note(args)
        if sum(1 for n in self.notes if n['charter'] == charter) >= MAX_NOTES_PER_CHARTER:
            raise ToolInputError(f'本章程笔记已达上限 {MAX_NOTES_PER_CHARTER} 条')
        note = {'charter': charter, 'text': text}
        self.notes.append(note)
        return note

    def add_report(self, charter: str, args: dict, evidence: dict | None) -> DefectReport:
        fields = parse_report_defect(args)
        if not evidence or not evidence.get('annotated'):
            raise ToolInputError('还没有可作为证据的观察，无法登记缺陷')
        if sum(1 for r in self.reports if r.charter == charter) >= MAX_REPORTS_PER_CHARTER:
            raise ToolInputError(f'本章程缺陷报告已达上限 {MAX_REPORTS_PER_CHARTER} 条')
        report = DefectReport(id=f'D{len(self.reports) + 1:03d}', charter=charter, evidence=dict(evidence), **fields)
        self.reports.append(report)
        return report

    def notes_for_prompt(self) -> str:
        '''Notes only (never earlier defect reports), for carrying UI knowledge into the next charter.'''
        return '\n'.join(f'- [{n["charter"]}] {n["text"]}' for n in self.notes)


NOTE_TOOL = {
    'name': 'note',
    'description': '记录界面或功能发现（控件位置、菜单结构、行为），供后续章程参考。这不是缺陷报告。',
    'input_schema': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']},
}
DEFECT_TOOL = {
    'name': 'report_defect',
    'description': '报告一个你确认的缺陷。先重现一次并核对手册；证据是最新一次观察的截图，所以要在看到缺陷出现的那次观察之后、且本轮没有其他动作时调用。',
    'input_schema': {
        'type': 'object',
        'properties': {
            'title': {'type': 'string'},
            'steps': {'type': 'array', 'items': {'type': 'string'}, 'description': '从软件初始状态开始的复现步骤'},
            'expected': {'type': 'string', 'description': '期望行为'},
            'expected_source': {'type': 'string', 'description': 'manual:<手册章节> 或 general（通用软件准则）'},
            'actual': {'type': 'string', 'description': '实际行为'},
            'severity': {'type': 'string', 'enum': list(SEVERITIES)},
        },
        'required': ['title', 'steps', 'expected', 'expected_source', 'actual', 'severity'],
    },
}


def make_handlers(findings: Findings, charter_id: str) -> dict:
    '''Agent handlers for note / report_defect, bound to one charter.'''

    def note(args: dict, obs: dict | None) -> str:
        findings.add_note(charter_id, args)
        return '已记录笔记。'

    def defect(args: dict, obs: dict | None) -> str:
        report = findings.add_report(charter_id, args, obs)
        return f'已登记缺陷 {report.id}，证据为当前观察截图。'

    return {'note': note, 'report_defect': defect}
