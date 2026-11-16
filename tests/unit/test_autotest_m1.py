from __future__ import annotations

import pytest

from testing_platform.autotest.agent import ToolInputError
from testing_platform.autotest.defects import (
    MAX_NOTE_CHARS, MAX_NOTES_PER_CHARTER, MAX_REPORTS_PER_CHARTER, Findings, parse_note, parse_report_defect,
)

GOOD = {'title': '标题', 'steps': ['打开设置', '点击应用'], 'expected': '按钮禁用', 'expected_source': 'manual:界面',
        'actual': '按钮仍可用', 'severity': 'medium'}
EVIDENCE = {'screenshot': 'a.png', 'annotated': 'a-marked.png'}


# ---- report_defect / note validation -------------------------------------------------------

def test_parse_report_defect_accepts_valid_and_strips():
    out = parse_report_defect({**GOOD, 'title': '  标题  ', 'steps': [' 打开设置 ']})
    assert out['title'] == '标题' and out['steps'] == ['打开设置'] and out['severity'] == 'medium'
    assert parse_report_defect({**GOOD, 'expected_source': 'general'})['expected_source'] == 'general'


def test_parse_report_defect_rejects_bad_input():
    bad = [{k: v for k, v in GOOD.items() if k != key} for key in GOOD]  # each field missing in turn
    bad += [{**GOOD, 'steps': []}, {**GOOD, 'steps': ['ok', '']}, {**GOOD, 'steps': '一步'},
            {**GOOD, 'severity': 'critical'}, {**GOOD, 'expected_source': 'manual:'},
            {**GOOD, 'expected_source': '我觉得'}, {**GOOD, 'actual': 'x' * 5000}, {**GOOD, 'title': ' '}]
    for args in bad:
        with pytest.raises(ToolInputError):
            parse_report_defect(args)
    with pytest.raises(ToolInputError):
        parse_report_defect([])


def test_parse_note_requires_short_text():
    assert parse_note({'text': ' 设置在工具菜单 '}) == '设置在工具菜单'
    for args in ({}, {'text': ''}, {'text': 'x' * (MAX_NOTE_CHARS + 1)}):
        with pytest.raises(ToolInputError):
            parse_note(args)


# ---- findings book -----------------------------------------------------------------------

def test_findings_numbers_reports_and_attaches_evidence():
    f = Findings()
    r1 = f.add_report('C1', GOOD, EVIDENCE)
    r2 = f.add_report('C2', GOOD, EVIDENCE)
    assert (r1.id, r2.id) == ('D001', 'D002') and r1.charter == 'C1' and r1.evidence == EVIDENCE
    assert r1.evidence is not EVIDENCE and f.reports == [r1, r2]
    assert r1.to_dict()['title'] == '标题'


def test_findings_rejects_report_without_evidence_or_with_bad_fields():
    f = Findings()
    for evidence in (None, {}):
        with pytest.raises(ToolInputError):
            f.add_report('C1', GOOD, evidence)
    with pytest.raises(ToolInputError):
        f.add_report('C1', {**GOOD, 'severity': 'x'}, EVIDENCE)
    assert f.reports == []


def test_findings_limits_reports_per_charter():
    f = Findings()
    for _ in range(MAX_REPORTS_PER_CHARTER):
        f.add_report('C1', GOOD, EVIDENCE)
    with pytest.raises(ToolInputError):
        f.add_report('C1', GOOD, EVIDENCE)
    f.add_report('C2', GOOD, EVIDENCE)
    assert len(f.reports) == MAX_REPORTS_PER_CHARTER + 1


def test_findings_limits_notes_per_charter():
    f = Findings()
    for i in range(MAX_NOTES_PER_CHARTER):
        f.add_note('C1', {'text': f'笔记{i}'})
    with pytest.raises(ToolInputError):
        f.add_note('C1', {'text': '多出来的'})
    f.add_note('C2', {'text': '另一章程'})
    assert len(f.notes) == MAX_NOTES_PER_CHARTER + 1


def test_notes_for_prompt_carries_notes_but_not_defect_reports():
    f = Findings()
    assert f.notes_for_prompt() == ''
    f.add_note('C1', {'text': '设置页有四个标签'})
    f.add_report('C1', {**GOOD, 'title': '独特缺陷标题'}, EVIDENCE)
    f.add_note('C2', {'text': '搜索框在工具栏右侧'})
    text = f.notes_for_prompt()
    assert '[C1] 设置页有四个标签' in text and '[C2] 搜索框在工具栏右侧' in text
    assert '独特缺陷标题' not in text


# ---- agent with framework-side handlers (note / report_defect) -------------------------------

import json
from types import SimpleNamespace

from testing_platform.autotest.agent import TOOLS, Agent
from testing_platform.autotest.model import Usage

NOTE_TOOL = {'name': 'note', 'description': 'n', 'input_schema': {'type': 'object', 'properties': {'text': {'type': 'string'}}}}
DEFECT_TOOL = {'name': 'report_defect', 'description': 'd', 'input_schema': {'type': 'object', 'properties': {}}}


class Block(dict):
    def model_dump(self, exclude_none=True):
        return dict(self)


def use(name, args, tid):
    return Block(type='tool_use', id=tid, name=name, input=args)


class HandlerModel:
    model = '[REDACTED]'
    effort = 'medium'

    def __init__(self, turns):
        self.turns = list(turns)
        self.usage = Usage()
        self.requests = []
        self.systems = []
        self.tool_names = []

    def create(self, system, messages, tools):
        self.requests.append(json.loads(json.dumps(messages, default=str)))
        self.systems.append(system)
        self.tool_names.append([t['name'] for t in tools])
        content, stop = self.turns.pop(0)
        self.usage.add(SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                       cache_creation_input_tokens=0))
        return SimpleNamespace(content=content, stop_reason=stop, usage=Block(input_tokens=10))


class HandlerDesktop:
    def __init__(self, png):
        self.png = png
        self.calls = []

    def call(self, op, timeout=None, **args):
        self.calls.append(op)
        if op == 'observe':
            return {'frame': {'left': 0, 'top': 0, 'scale': 1.0}, 'windows': [{'title': 'App', 'foreground': True}],
                    'elements': [], 'truncated': False, 'annotated': str(self.png), 'screenshot': str(self.png)}
        return {}


@pytest.fixture
def shot(tmp_path):
    from PIL import Image
    path = tmp_path / 'obs.png'
    Image.new('RGB', (4, 4)).save(path)
    return path


def make_agent(model, desktop, tmp_path, findings, **kw):
    def note(args, obs):
        return '已记录：' + findings.add_note('C1', args)['text']

    def defect(args, obs):
        return '已登记 ' + findings.add_report('C1', args, obs).id

    return Agent(model, desktop, tmp_path, handlers={'note': note, 'report_defect': defect},
                 extra_tools=[NOTE_TOOL, DEFECT_TOOL], **kw)


def results_of(model, request_index):
    return {r['tool_use_id']: r for r in model.requests[request_index][-1]['content']}


def test_handlers_cost_no_action_and_use_latest_observation(tmp_path, shot):
    findings = Findings()
    model = HandlerModel([
        ([use('note', {'text': '设置在工具菜单'}, 'a1'), use('report_defect', GOOD, 'a2')], 'tool_use'),
        ([use('finish', {'status': 'completed', 'summary': '探索结束'}, 'a3')], 'tool_use'),
    ])
    desktop = HandlerDesktop(shot)
    result = make_agent(model, desktop, tmp_path, findings).run('探索')
    assert result.outcome == 'completed' and result.actions == 0
    assert desktop.calls == ['observe']
    assert findings.reports[0].evidence == {'screenshot': str(shot), 'annotated': str(shot)}
    assert [n['text'] for n in findings.notes] == ['设置在工具菜单']
    res = results_of(model, 1)
    assert not res['a1']['is_error'] and not res['a2']['is_error']
    assert '已登记 D001' in res['a2']['content'][0]['text']


def test_report_defect_after_action_in_same_turn_is_rejected(tmp_path, shot):
    findings = Findings()
    model = HandlerModel([
        ([use('click', {'element_id': 'e1'}, 'b1'), use('note', {'text': '点击后出现对话框'}, 'b2'),
          use('report_defect', GOOD, 'b3')], 'tool_use'),
        ([use('report_defect', GOOD, 'b4')], 'tool_use'),
        ([use('finish', {'status': 'completed', 'summary': '完成'}, 'b5')], 'tool_use'),
    ])
    desktop = HandlerDesktop(shot)
    result = make_agent(model, desktop, tmp_path, findings).run('探索')
    assert result.actions == 1 and desktop.calls == ['observe', 'click_element', 'observe']
    res = results_of(model, 1)
    assert not res['b2']['is_error']
    assert res['b3']['is_error'] and '未接受' in res['b3']['content'][0]['text']
    assert [r.id for r in findings.reports] == ['D001'] and len(findings.notes) == 1


def test_handler_input_error_is_reported_not_raised(tmp_path, shot):
    findings = Findings()
    model = HandlerModel([
        ([use('report_defect', {**GOOD, 'severity': 'x'}, 'c1')], 'tool_use'),
        ([use('finish', {'status': 'failed', 'summary': '放弃'}, 'c2')], 'tool_use'),
    ])
    result = make_agent(model, HandlerDesktop(shot), tmp_path, findings).run('探索')
    assert result.tool_errors == 1 and result.actions == 0 and findings.reports == []
    assert results_of(model, 1)['c1']['is_error'] is True


def test_extra_tools_and_system_prompt_reach_the_model(tmp_path, shot):
    model = HandlerModel([([use('finish', {'status': 'completed', 'summary': 'ok'}, 'd1')], 'tool_use')])
    make_agent(model, HandlerDesktop(shot), tmp_path, Findings(),
               system_prompt='探索 {max_actions} 动作 {max_minutes} 分钟').run('t')
    assert model.tool_names[0] == [t['name'] for t in TOOLS] + ['note', 'report_defect']
    assert model.systems[0] == '探索 30 动作 8.0 分钟'


def test_default_agent_keeps_m0_tools_and_prompt(tmp_path, shot):
    model = HandlerModel([([use('finish', {'status': 'completed', 'summary': 'ok'}, 'e1')], 'tool_use')])
    Agent(model, HandlerDesktop(shot), tmp_path).run('t')
    assert model.tool_names[0] == [t['name'] for t in TOOLS]
    assert '测试执行员' in model.systems[0]


# ---- charter planning ------------------------------------------------------------------------

from testing_platform.autotest.explore import (
    CHARTER_TOOL, MAX_CHARTERS, MIN_CHARTERS, Charter, PlanError, load_manual, parse_charters, plan_charters,
)


def charter(i, **over):
    base = {'id': f'C{i}', 'title': f'章程{i}', 'area': f'功能区{i}', 'focus': '核对手册行为',
            'manual_refs': ['Application Settings'], 'max_actions': 30}
    return {**base, **over}


def charters(n=4):
    return {'charters': [charter(i) for i in range(1, n + 1)]}


def test_parse_charters_accepts_valid_plan():
    out = parse_charters(charters(5))
    assert len(out) == 5 and isinstance(out[0], Charter) and out[0].id == 'C1' and out[0].max_actions == 30
    assert out[0].to_dict()['manual_refs'] == ['Application Settings']


def test_parse_charters_rejects_bad_plans():
    bad = [{}, {'charters': 'x'}, charters(MIN_CHARTERS - 1), charters(MAX_CHARTERS + 1)]
    for key in ('id', 'title', 'area', 'focus', 'manual_refs', 'max_actions'):
        plan = charters()
        del plan['charters'][1][key]
        bad.append(plan)
    for over in ({'max_actions': 0}, {'max_actions': 5000}, {'max_actions': True}, {'max_actions': '30'},
                 {'manual_refs': []}, {'manual_refs': ['']}, {'title': ' '}):
        plan = charters()
        plan['charters'][0] = charter(1, **over)
        bad.append(plan)
    dup = charters()
    dup['charters'][2]['id'] = 'C1'
    bad += [dup, {'charters': [1, 2, 3, 4]}]
    for plan in bad:
        with pytest.raises(PlanError):
            parse_charters(plan)
    with pytest.raises(PlanError):
        parse_charters(None)


class PlanModel:
    def __init__(self, content, stop='tool_use'):
        self.content, self.stop, self.calls = content, stop, []

    def create(self, system, messages, tools):
        self.calls.append((system, messages, tools))
        return SimpleNamespace(content=self.content, stop_reason=self.stop)


def test_plan_charters_uses_forced_tool_and_manual_text():
    model = PlanModel([Block(type='text', text='好的'), use('submit_charters', charters(4), 'p1')])
    out = plan_charters(model, '手册全文XYZ', '测试 KeePassXC')
    system, messages, tools = model.calls[0]
    assert [c.id for c in out] == ['C1', 'C2', 'C3', 'C4']
    assert tools == [CHARTER_TOOL] and '手册全文XYZ' in messages[0]['content'] and '测试 KeePassXC' in messages[0]['content']


def test_plan_charters_fails_without_tool_call_or_with_invalid_plan():
    with pytest.raises(PlanError):
        plan_charters(PlanModel([Block(type='text', text='我来规划')], 'end_turn'), 'm', 'g')
    with pytest.raises(PlanError):
        plan_charters(PlanModel([use('submit_charters', charters(2), 'p2')]), 'm', 'g')
    with pytest.raises(PlanError):
        plan_charters(PlanModel([use('other_tool', charters(4), 'p3')]), 'm', 'g')


def test_invalid_plan_error_keeps_stop_reason_and_what_the_model_sent():
    model = PlanModel([use('submit_charters', charters(2), 'p4')], 'max_tokens')
    with pytest.raises(PlanError) as info:
        plan_charters(model, 'm', 'g')
    message = str(info.value)
    assert '4 到 6' in message and 'stop_reason=max_tokens' in message and '章程2' in message


def test_load_manual_concatenates_adoc_and_rejects_empty_dir(tmp_path):
    with pytest.raises(PlanError):
        load_manual(tmp_path)
    (tmp_path / 'b.adoc').write_text('第二份', encoding='utf-8')
    (tmp_path / 'a.adoc').write_text('第一份', encoding='utf-8')
    (tmp_path / 'ignored.png').write_bytes(b'x')
    text = load_manual(tmp_path)
    assert text.index('a.adoc') < text.index('b.adoc') and '第一份' in text and '第二份' in text


# ---- charter execution and total budget ------------------------------------------------------

import contextlib

from testing_platform.autotest.explore import TotalBudget, charter_task, run_exploration


class FakeSession:
    def __init__(self, shot, fail=()):
        self.shot, self.fail = shot, fail
        self.opened, self.closed = [], []

    @contextlib.contextmanager
    def __call__(self, charter, charter_dir):
        if charter.id in self.fail:
            raise RuntimeError('launch failed')
        self.opened.append(charter.id)
        try:
            yield HandlerDesktop(self.shot)
        finally:
            self.closed.append(charter.id)


def two_charters():
    return [Charter(f'C{i}', f'章程{i}', f'区{i}', '关注点', ['界面'], 30) for i in (1, 2)]


def finish_turn(tid):
    return ([use('finish', {'status': 'completed', 'summary': '完成'}, tid)], 'tool_use')


def test_charter_task_contains_goal_charter_notes_and_manual():
    text = charter_task('目标X', two_charters()[0], '- [C0] 笔记Y', '手册Z')
    for part in ('目标X', 'C1', '章程1', '区1', '关注点', '界面', '笔记Y', '手册Z'):
        assert part in text
    assert '前序章程' not in charter_task('目标X', two_charters()[0], '', '手册Z')


def test_next_charter_gets_notes_but_not_reports(tmp_path, shot):
    model = HandlerModel([
        ([use('note', {'text': '设置在工具菜单'}, 'n1'), use('report_defect', {**GOOD, 'title': '独特缺陷标题'}, 'n2'),
          use('finish', {'status': 'completed', 'summary': '完成'}, 'n3')], 'tool_use'),
        finish_turn('n4'),
    ])
    session = FakeSession(shot)
    records, findings = run_exploration(model, two_charters(), '目标', '手册全文', tmp_path, session)
    assert [r['status'] for r in records] == ['done', 'done'] and session.closed == ['C1', 'C2']
    assert (records[0]['notes'], records[0]['reports'], records[1]['notes']) == (1, 1, 0)
    second = model.requests[1][0]['content'][0]['text']
    assert '设置在工具菜单' in second and '手册全文' in second and '独特缺陷标题' not in second
    assert (tmp_path / 'charter-1' / 'result.json').exists() and (tmp_path / 'charter-2' / 'result.json').exists()
    assert [r.charter for r in findings.reports] == ['C1']


def test_total_budget_skips_remaining_charters(tmp_path, shot):
    model = HandlerModel([([use('click', {'element_id': 'e1'}, 's1')], 'tool_use'), finish_turn('s2')])
    session = FakeSession(shot)
    records, _ = run_exploration(model, two_charters(), '目标', '手册', tmp_path, session,
                                 total=TotalBudget(max_actions=1))
    assert records[0]['run']['actions'] == 1 and records[0]['budget']['max_actions'] == 1
    assert records[1]['status'] == 'skipped_budget' and records[1]['reason'] == 'actions'
    assert session.opened == ['C1']


def test_charter_budget_is_capped_by_remaining_total(tmp_path, shot):
    model = HandlerModel([finish_turn('t1'), finish_turn('t2')])
    records, _ = run_exploration(model, two_charters(), '目标', '手册', tmp_path, FakeSession(shot),
                                 total=TotalBudget(max_actions=5, max_model_calls=1))
    assert records[0]['budget']['max_actions'] == 5 and records[0]['budget']['max_model_calls'] == 1
    assert records[1]['status'] == 'skipped_budget' and records[1]['reason'] == 'model_calls'


def test_session_failure_is_recorded_and_next_charter_still_runs(tmp_path, shot):
    model = HandlerModel([finish_turn('f1')])
    session = FakeSession(shot, fail=('C1',))
    records, _ = run_exploration(model, two_charters(), '目标', '手册', tmp_path, session)
    assert records[0]['status'] == 'error' and 'launch failed' in records[0]['error'] and 'run' not in records[0]
    assert records[1]['status'] == 'done' and records[1]['outcome'] == 'completed'
    assert session.opened == ['C2'] and session.closed == ['C2']


# ---- duplicate grouping ------------------------------------------------------------------------

from testing_platform.autotest.explore import DedupError, dedupe_reports, parse_groups


def three_reports():
    f = Findings()
    for title in ('按钮仍可用', '按钮没有禁用', '搜索选中项不对'):
        f.add_report('C1', {**GOOD, 'title': title}, EVIDENCE)
    return f.reports


class TextModel:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def create(self, system, messages, tools):
        self.calls.append((system, messages, tools))
        if self.error:
            raise self.error
        return SimpleNamespace(content=[Block(type='text', text=self.text)], stop_reason='end_turn')


def test_parse_groups_sorts_and_requires_each_id_once():
    ids = ['D001', 'D002', 'D003']
    assert parse_groups('结果：{"groups": [["D003"], ["D002", "D001"]]}', ids) == [['D001', 'D002'], ['D003']]
    for bad in ('没有json', '{"groups": 1}', '{"groups": [["D001"], ["D002"]]}',
                '{"groups": [["D001", "D002"], ["D002", "D003"]]}', '{"groups": [["D001"], [], ["D002", "D003"]]}',
                '{"groups": [["D001", "D002", "D003", "D009"]]}', '{坏的}'):
        with pytest.raises(DedupError):
            parse_groups(bad, ids)


def test_dedupe_merges_groups_and_sends_no_evidence_or_tools():
    model = TextModel('{"groups": [["D002", "D001"], ["D003"]]}')
    out = dedupe_reports(model, three_reports())
    assert out == {'undeduped': False, 'groups': [{'keep': 'D001', 'merged': ['D002']},
                                                  {'keep': 'D003', 'merged': []}]}
    system, messages, tools = model.calls[0]
    assert tools == [] and '搜索选中项不对' in messages[0]['content'] and 'a-marked.png' not in messages[0]['content']


def test_dedupe_skips_model_for_fewer_than_two_reports():
    model = TextModel('不该被调用')
    assert dedupe_reports(model, []) == {'undeduped': False, 'groups': []}
    one = three_reports()[:1]
    assert dedupe_reports(model, one)['groups'] == [{'keep': 'D001', 'merged': []}] and model.calls == []


def test_dedupe_failure_keeps_every_report_and_marks_undeduped():
    for model in (TextModel(error=ConnectionError('relay down')), TextModel('{"groups": [["D001"]]}'),
                  TextModel('我觉得都不一样')):
        out = dedupe_reports(model, three_reports())
        assert out['undeduped'] is True and out['error']
        assert out['groups'] == [{'keep': i, 'merged': []} for i in ('D001', 'D002', 'D003')]


# ---- scoring -----------------------------------------------------------------------------------

from testing_platform.autotest.explore import ScoreError, score_exploration, score_run


def score_inputs():
    reports = {'reports': [{'id': f'D00{i}'} for i in (1, 2, 3, 4)],
               'dedupe': {'undeduped': False, 'groups': [{'keep': 'D001', 'merged': ['D002']},
                                                         {'keep': 'D003', 'merged': []},
                                                         {'keep': 'D004', 'merged': []}]}}
    truth = {'defects': [{'id': 'T1', 'repro_status': 'confirmed'}, {'id': 'T2', 'repro_status': 'confirmed'},
                         {'id': 'T3', 'repro_status': 'excluded'}, {'id': 'T4', 'repro_status': 'pending'}]}
    plan = [{'id': f'C{i}', 'manual_refs': [f'章节{i}', '公共']} for i in (1, 2, 3)]
    usage = {'input_tokens': 1000, 'output_tokens': 100, 'cache_read_input_tokens': 0,
             'cache_creation_input_tokens': 0, 'calls': 5, 'estimated_cost_usd': 0.5}
    records = [{'id': 'C1', 'status': 'done', 'run': {'actions': 10, 'model_calls': 5, 'seconds': 100.0, 'usage': usage}},
               {'id': 'C2', 'status': 'skipped_budget', 'reason': 'actions'},
               {'id': 'C3', 'status': 'error', 'error': 'x'}]
    return reports, truth, plan, records


def judge(*items):
    return {'judgements': [{'report_id': r, 'label': lab, 'truth_id': t, 'basis': '人工复现'} for r, lab, t in items]}


def test_score_recall_precision_and_unjudged():
    reports, truth, plan, records = score_inputs()
    out = score_exploration(reports, truth, judge(('D001', 'known', 'T1'), ('D003', 'not_defect', None)), plan, records)
    assert out['reports']['counts'] == {'known': 1, 'new': 0, 'not_defect': 1, 'undetermined': 0}
    assert out['reports']['unjudged'] == ['D004'] and out['reports']['after_dedupe'] == 3 and out['reports']['total'] == 4
    assert out['precision'] == 0.5
    assert out['recall'] == {'found': ['T1'], 'missed': ['T2'], 'confirmed_total': 2, 'value': 0.5}


def test_score_undetermined_excluded_and_unconfirmed_truth_not_counted_for_recall():
    reports, truth, plan, records = score_inputs()
    out = score_exploration(reports, truth, judge(('D001', 'known', 'T3'), ('D003', 'undetermined', None),
                                                   ('D004', 'new', None)), plan, records)
    assert out['precision'] == 1.0 and out['reports']['counts']['undetermined'] == 1
    assert out['recall'] == {'found': [], 'missed': ['T1', 'T2'], 'confirmed_total': 2, 'value': 0.0}


def test_score_without_judgements_leaves_everything_unjudged():
    reports, truth, plan, records = score_inputs()
    out = score_exploration(reports, truth, {}, plan, records)
    assert out['precision'] is None and out['reports']['unjudged'] == ['D001', 'D003', 'D004']
    assert out['recall']['value'] == 0.0


def test_score_coverage_and_cost():
    reports, truth, plan, records = score_inputs()
    out = score_exploration(reports, truth, {}, plan, records)
    assert out['coverage'] == {'charters_total': 3, 'done': 1, 'skipped_budget': 1, 'error': 1,
                               'manual_refs_covered': ['公共', '章节1']}
    assert out['cost'] == {'actions': 10, 'model_calls': 5, 'seconds': 100.0, 'input_tokens': 1000,
                           'output_tokens': 100, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0,
                           'estimated_cost_usd': 0.5}
    records[0]['run']['usage']['estimated_cost_usd'] = None
    assert score_exploration(reports, truth, {}, plan, records)['cost']['estimated_cost_usd'] is None


def test_score_rejects_bad_judgements_and_truth():
    reports, truth, plan, records = score_inputs()
    bad = [judge(('D002', 'not_defect', None)), judge(('D009', 'not_defect', None)),
           judge(('D001', 'maybe', None)), judge(('D001', 'known', None)), judge(('D001', 'known', 'T9')),
           judge(('D001', 'not_defect', None), ('D001', 'new', None)),
           {'judgements': [{'report_id': 'D001', 'label': 'new', 'basis': ' '}]}]
    for judgement in bad:
        with pytest.raises(ScoreError):
            score_exploration(reports, truth, judgement, plan, records)
    truth['defects'][0]['repro_status'] = 'maybe'
    with pytest.raises(ScoreError):
        score_exploration(reports, truth, {}, plan, records)


def test_score_run_reads_run_directory(tmp_path):
    reports, truth, plan, records = score_inputs()
    write = lambda path, data: path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    write(tmp_path / 'plan.json', {'charters': plan})
    write(tmp_path / 'reports.json', reports)
    write(tmp_path / 'truth.json', truth)
    write(tmp_path / 'judge.json', judge(('D001', 'known', 'T1')))
    for i, record in enumerate(records, 1):
        (tmp_path / f'charter-{i}').mkdir()
        write(tmp_path / f'charter-{i}' / 'result.json', record)
    direct = score_exploration(reports, truth, judge(('D001', 'known', 'T1')), plan, records)
    assert score_run(tmp_path, tmp_path / 'truth.json', tmp_path / 'judge.json') == direct
    assert score_run(tmp_path, tmp_path / 'truth.json', tmp_path / 'missing.json')['precision'] is None


# ---- exploration system prompt ------------------------------------------------------------------

from testing_platform.autotest.explore import EXPLORE_SYSTEM_PROMPT

# Symptom phrases of the candidate defects in prd.md; the prompt must never hint at them.
SYMPTOM_WORDS = ('Tab 顺序', 'Tab顺序', 'TOTP', '搜索后', '默认选中', '重启后', '应用按钮', '按钮仍可用', '隐藏')


def test_explore_prompt_formats_and_names_framework_tools():
    text = EXPLORE_SYSTEM_PROMPT.format(max_actions=30, max_minutes=8.0)
    assert '30 个动作' in text and '8.0 分钟' in text
    assert 'note' in text and 'report_defect' in text and 'finish' in text
    assert '{' not in text and '}' not in text


def test_explore_prompt_does_not_hint_at_known_defects():
    for word in SYMPTOM_WORDS:
        assert word not in EXPLORE_SYSTEM_PROMPT, word


# ---- whole run and command line -----------------------------------------------------------------

from pathlib import Path

from testing_platform.autotest.explore import default_goal, explore_run, main, render_report


def whole_run_model():
    report = lambda title, tid: use('report_defect', {**GOOD, 'title': title}, tid)
    done = lambda tid: use('finish', {'status': 'completed', 'summary': '完成'}, tid)
    return HandlerModel([
        ([use('submit_charters', charters(4), 'w0')], 'tool_use'),
        ([use('note', {'text': '设置在工具菜单'}, 'w1'), report('保存后按钮状态不对', 'w2'), done('w3')], 'tool_use'),
        ([report('保存后按钮状态依旧不对', 'w4'), done('w5')], 'tool_use'),
        ([done('w6')], 'tool_use'),
        ([done('w7')], 'tool_use'),
        ([Block(type='text', text='{"groups": [["D001", "D002"]]}')], 'end_turn'),
    ])


def test_explore_run_writes_all_outputs_and_counts_overhead(tmp_path, shot):
    model = whole_run_model()
    summary = explore_run(model, '手册全文', default_goal('pw'), tmp_path, FakeSession(shot))
    plan = json.loads((tmp_path / 'plan.json').read_text(encoding='utf-8'))
    reports = json.loads((tmp_path / 'reports.json').read_text(encoding='utf-8'))
    notes = json.loads((tmp_path / 'notes.json').read_text(encoding='utf-8'))
    assert [c['id'] for c in plan['charters']] == ['C1', 'C2', 'C3', 'C4'] and plan['usage']['calls'] == 1
    assert [r['id'] for r in reports['reports']] == ['D001', 'D002'] and reports['usage']['calls'] == 1
    assert reports['dedupe'] == {'undeduped': False, 'groups': [{'keep': 'D001', 'merged': ['D002']}]}
    assert notes == [{'charter': 'C1', 'text': '设置在工具菜单'}]
    assert model.tool_names[-1] == [] and model.tool_names[0] == ['submit_charters']
    assert 'report_defect' in model.tool_names[1] and '探索式测试员' in model.systems[1]
    assert summary['reports'] == {'total': 2, 'after_dedupe': 1, 'undeduped': False} and summary['notes'] == 1
    assert summary['coverage']['done'] == 4 and summary['cost']['model_calls'] == 6
    assert summary['cost']['input_tokens'] == 60
    assert json.loads((tmp_path / 'summary.json').read_text(encoding='utf-8')) == summary
    md = (tmp_path / 'report.md').read_text(encoding='utf-8')
    assert '去重后 1 条' in md and '保存后按钮状态不对' in md and '合并的重复报告：D002' in md
    assert '保存后按钮状态依旧不对' not in md and 'Application Settings' in md


def test_explore_run_stops_on_invalid_plan_without_touching_the_app(tmp_path, shot):
    model = HandlerModel([([use('submit_charters', charters(2), f'x{i}')], 'tool_use') for i in range(3)])
    session = FakeSession(shot)
    with pytest.raises(PlanError):
        explore_run(model, '手册', '目标', tmp_path, session)
    assert session.opened == [] and not (tmp_path / 'plan.json').exists()
    failed = json.loads((tmp_path / 'plan-failed.json').read_text(encoding='utf-8'))
    assert [f['attempt'] for f in failed['failures']] == [1, 2, 3] and failed['usage']['calls'] == 3


def test_plan_retries_with_feedback_until_valid():
    model = HandlerModel([
        ([Block(type='text', text='我先想一想')], 'end_turn'),
        ([use('submit_charters', charters(2), 'r2')], 'tool_use'),
        ([use('submit_charters', charters(5), 'r3')], 'tool_use'),
    ])
    log = []
    out = plan_charters(model, '手册', '目标', log=log)
    assert len(out) == 5 and [f['attempt'] for f in log] == [1, 2]
    assert '没有调用' in log[0]['error'] and '我先想一想' in log[0]['error'] and '4 到 6' in log[1]['error']
    second, third = model.requests[1], model.requests[2]
    assert second[-1]['content'][0]['type'] == 'text' and 'submit_charters' in second[-1]['content'][0]['text']
    result = third[-1]['content'][0]
    assert result['type'] == 'tool_result' and result['tool_use_id'] == 'r2' and result['is_error'] is True
    assert third[-2]['role'] == 'assistant' and third[-2]['content'][0]['id'] == 'r2'


def test_render_report_without_reports():
    md = render_report([charter(1)], [{'id': 'C1', 'title': '章程1', 'status': 'skipped_budget'}], [],
                       {'undeduped': False, 'groups': []}, Path('.'))
    assert '没有报告缺陷' in md and 'skipped_budget' in md and '覆盖的手册章节' in md


def test_default_goal_gives_password_and_no_defect_hints():
    goal = default_goal('Secret@1')
    assert 'Secret@1' in goal and '手册' in goal
    for word in SYMPTOM_WORDS:
        assert word not in goal, word


def test_keepassxc_session_targets_pid_and_always_stops(tmp_path, monkeypatch):
    import testing_platform.autotest.apps.keepassxc as kpxc
    import testing_platform.autotest.desktop.client as client
    from testing_platform.autotest.explore import keepassxc_session

    log = []

    class Env:
        def __init__(self, app_dir, seed_db, password, run_dir):
            log.append(('env', Path(run_dir).name, password))
            self.fail = Path(run_dir).parent.name == 'bad'

        def reset(self):
            log.append('reset')

        def launch(self):
            if self.fail:
                raise RuntimeError('window did not appear')
            return 42

        def stop(self):
            log.append('stop')
            return [{'pid': 42, 'exited': True}]

    class Client:
        def __init__(self, out_dir):
            log.append(('client', Path(out_dir).name))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            log.append('client_closed')

        def call(self, op, **args):
            log.append((op, args))

    monkeypatch.setattr(kpxc, 'KeePassXCEnv', Env)
    monkeypatch.setattr(client, 'DesktopClient', Client)
    session = keepassxc_session(tmp_path / 'app', tmp_path / 'seed.kdbx', 'pw')
    (tmp_path / 'ok').mkdir()
    with session(two_charters()[0], tmp_path / 'ok') as desktop:
        assert isinstance(desktop, Client)
    assert log == [('env', 'data', 'pw'), 'reset', ('client', 'shots'), ('set_target', {'pids': [42]}),
                   'client_closed', 'stop']
    assert json.loads((tmp_path / 'ok' / 'stop.json').read_text(encoding='utf-8')) == [{'pid': 42, 'exited': True}]
    log.clear()
    (tmp_path / 'bad').mkdir()
    with pytest.raises(RuntimeError):
        with session(two_charters()[0], tmp_path / 'bad'):
            pass
    assert log == [('env', 'data', 'pw'), 'reset', 'stop']


def test_remote_session_resets_launches_targets_and_always_stops(tmp_path, monkeypatch):
    import testing_platform.autotest.desktop.remote_client as rc
    from testing_platform.autotest.explore import remote_session

    log = []

    class Client:
        fail_launch = False

        def __init__(self, host, port, token, out_dir):
            log.append(('connect', host, port, Path(out_dir).name))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            log.append('closed')

        def call(self, op, timeout=None, **args):
            log.append((op, args))
            if op == 'kpxc_launch':
                if Client.fail_launch:
                    raise RuntimeError('window did not appear')
                return {'pid': 77}
            if op == 'kpxc_stop':
                return {'log': [{'pid': 77, 'exited': True}]}
            return {}

    monkeypatch.setattr(rc, 'RemoteDesktopClient', Client)
    session = remote_session('10.0.0.5', 8765, 'tok', 'keepassxc-m1/seed.kdbx', 'pw')
    (tmp_path / 'ok').mkdir()
    with session(two_charters()[0], tmp_path / 'ok') as desktop:
        assert isinstance(desktop, Client)
    assert log == [('connect', '10.0.0.5', 8765, 'shots'),
                   ('kpxc_reset', {'seed': 'keepassxc-m1/seed.kdbx', 'password': 'pw'}),
                   ('kpxc_launch', {}), ('set_target', {'pids': [77]}), ('kpxc_stop', {}), 'closed']
    assert json.loads((tmp_path / 'ok' / 'stop.json').read_text(encoding='utf-8')) == {
        'log': [{'pid': 77, 'exited': True}]}
    log.clear()
    Client.fail_launch = True
    (tmp_path / 'bad').mkdir()
    with pytest.raises(RuntimeError):
        with session(two_charters()[0], tmp_path / 'bad'):
            pass
    assert [e if isinstance(e, str) else e[0] for e in log] == ['connect', 'kpxc_reset', 'kpxc_launch',
                                                                'kpxc_stop', 'closed']


def test_main_refuses_host_desktop_without_remote_or_local(capsys, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'x')
    assert main([]) == 2
    assert '--remote' in capsys.readouterr().err


def test_main_score_writes_score_and_rejects_bad_judgement(tmp_path, shot, capsys):
    explore_run(whole_run_model(), '手册', '目标', tmp_path, FakeSession(shot))
    truth = {'defects': [{'id': 'T1', 'repro_status': 'confirmed'}, {'id': 'T2', 'repro_status': 'pending'}]}
    (tmp_path / 'truth.json').write_text(json.dumps(truth), encoding='utf-8')
    (tmp_path / 'judgement.json').write_text(json.dumps(judge(('D001', 'known', 'T1'))), encoding='utf-8')
    assert main(['--score', str(tmp_path), '--truth', str(tmp_path / 'truth.json')]) == 0
    score = json.loads((tmp_path / 'score.json').read_text(encoding='utf-8'))
    assert score['recall'] == {'found': ['T1'], 'missed': [], 'confirmed_total': 1, 'value': 1.0}
    assert score['precision'] == 1.0 and score['cost']['model_calls'] == 6
    (tmp_path / 'judgement.json').write_text(json.dumps(judge(('D002', 'new', None))), encoding='utf-8')
    assert main(['--score', str(tmp_path), '--truth', str(tmp_path / 'truth.json')]) == 2
    assert '评分失败' in capsys.readouterr().err
