'''Tests for the TCP front (remote_server) and its host-side client (remote_client) over loopback.'''

import json
import socket
import threading

import pytest

from testing_platform.autotest.desktop import remote_server
from testing_platform.autotest.desktop.client import ServiceError, ToolTimeout
from testing_platform.autotest.desktop.remote_client import RemoteDesktopClient

TOKEN = 't' * 24


class FakeDesktop:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.calls = []

    def call(self, op, timeout=None, **args):
        self.calls.append((op, timeout, args))
        if op == 'observe':
            raw = self.out_dir / 'obs-0001.png'
            marked = self.out_dir / 'obs-0001-marked.png'
            raw.write_bytes(b'raw-bytes')
            marked.write_bytes(b'marked-bytes')
            return {'screenshot': str(raw), 'annotated': str(marked), 'elements': []}
        if op == 'refuse':
            raise ServiceError('Refused', 'not the target')
        if op == 'hang':
            raise ToolTimeout('hang did not finish; service restarted')
        return {'echo': args}


@pytest.fixture
def server(tmp_path):
    guest = tmp_path / 'guest'
    guest.mkdir()
    fake = FakeDesktop(guest)
    lock = threading.Lock()
    srv = socket.create_server(('127.0.0.1', 0))
    port = srv.getsockname()[1]

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=remote_server.serve_connection,
                             args=(conn, fake, lock, guest, TOKEN), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    yield port, fake, guest
    srv.close()


def closed_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def make_client(port, tmp_path, token=TOKEN):
    return RemoteDesktopClient('127.0.0.1', port, token, tmp_path / 'host', default_timeout=5.0)


def test_call_round_trip_and_timeout_is_forwarded(server, tmp_path):
    port, fake, _ = server
    with make_client(port, tmp_path) as client:
        assert client.call('click_point', timeout=7, x=1.5, y=2) == {'echo': {'x': 1.5, 'y': 2}}
    assert fake.calls[-1] == ('click_point', 7, {'x': 1.5, 'y': 2})


def test_set_target_is_remembered(server, tmp_path):
    port, _, _ = server
    with make_client(port, tmp_path) as client:
        client.call('set_target', pids=[11, 22])
        assert client.target == [11, 22]


def test_observe_copies_screenshots_locally(server, tmp_path):
    port, _, _ = server
    local = tmp_path / 'host'
    with make_client(port, tmp_path) as client:
        obs = client.call('observe')
    assert (local / 'obs-0001.png').read_bytes() == b'raw-bytes'
    assert (local / 'obs-0001-marked.png').read_bytes() == b'marked-bytes'
    assert obs['screenshot'] == str(local / 'obs-0001.png')
    assert obs['annotated'] == str(local / 'obs-0001-marked.png')


def test_wrong_token_is_rejected_without_leaking_it(server, tmp_path):
    port, fake, _ = server
    bad = 'x' * 24
    client = make_client(port, tmp_path, token=bad)
    with pytest.raises(ServiceError) as info:
        client.start()
    assert info.value.kind == 'AuthFailed'
    assert bad not in str(info.value)
    assert fake.calls == []


def test_service_error_kind_is_preserved(server, tmp_path):
    port, _, _ = server
    with make_client(port, tmp_path) as client:
        with pytest.raises(ServiceError) as info:
            client.call('refuse')
    assert info.value.kind == 'Refused'
    assert info.value.message == 'not the target'


def test_service_timeout_is_forwarded_as_tool_timeout(server, tmp_path):
    port, _, _ = server
    with make_client(port, tmp_path) as client:
        with pytest.raises(ToolTimeout):
            client.call('hang')
        assert client.call('ping') == {'echo': {}}  # the connection stays usable


def test_unreachable_service_reports_connection_failed(tmp_path):
    client = make_client(closed_port(), tmp_path)
    with pytest.raises(ServiceError) as info:
        client.start()
    assert info.value.kind == 'ConnectionFailed'
    assert TOKEN not in str(info.value)


def test_dead_link_raises_tool_timeout_then_reconnects(server, tmp_path):
    port, _, _ = server
    with make_client(port, tmp_path) as client:
        client.call('ping')
        client.sock.shutdown(socket.SHUT_RDWR)
        with pytest.raises(ToolTimeout):
            client.call('ping')
        assert client.restarts == 1
        assert client.call('ping') == {'echo': {}}


def test_fetch_file_refuses_paths_outside_output_dir(tmp_path):
    guest = tmp_path / 'guest'
    guest.mkdir()
    inside = guest / 'a.png'
    inside.write_bytes(b'ok')
    outside = tmp_path / 'secret.txt'
    outside.write_text('secret')
    lock = threading.Lock()

    def fetch(path):
        line = json.dumps({'id': 1, 'op': 'fetch_file', 'args': {'path': str(path)}})
        return remote_server.execute(FakeDesktop(guest), lock, guest, line)

    assert fetch(inside)['ok'] is True
    for bad in (outside, guest / '..' / 'secret.txt', guest / 'missing.png', guest):
        resp = fetch(bad)
        assert resp['ok'] is False and resp['kind'] == 'Refused'


def test_execute_reports_bad_requests_instead_of_raising(tmp_path):
    resp = remote_server.execute(FakeDesktop(tmp_path), threading.Lock(), tmp_path, 'not json')
    assert resp['ok'] is False
    resp = remote_server.execute(FakeDesktop(tmp_path), threading.Lock(), tmp_path, json.dumps({'id': 3}))
    assert resp['ok'] is False and resp['id'] == 3


def test_execute_routes_extra_ops_and_falls_back_to_desktop(tmp_path):
    fake = FakeDesktop(tmp_path)
    lock = threading.Lock()
    seen = []

    def handler(args):
        seen.append((args, lock.locked()))
        return {'got': args}

    extra = {'kpxc_ping': handler}
    line = json.dumps({'id': 7, 'op': 'kpxc_ping', 'args': {'x': 1}})
    resp = remote_server.execute(fake, lock, tmp_path, line, extra)
    assert resp == {'id': 7, 'ok': True, 'result': {'got': {'x': 1}}}
    assert seen == [({'x': 1}, True)]
    assert fake.calls == []

    line = json.dumps({'id': 8, 'op': 'click', 'args': {'y': 2}})
    resp = remote_server.execute(fake, lock, tmp_path, line, extra)
    assert resp['ok'] is True and fake.calls == [('click', None, {'y': 2})]


def test_execute_reports_extra_handler_errors(tmp_path):
    def boom(args):
        raise RuntimeError('kpxc_reset must be called first')

    line = json.dumps({'id': 9, 'op': 'kpxc_boom', 'args': {}})
    resp = remote_server.execute(FakeDesktop(tmp_path), threading.Lock(), tmp_path, line, {'kpxc_boom': boom})
    assert resp['ok'] is False and resp['id'] == 9 and resp['kind'] == 'RuntimeError'


def test_guest_reset_refuses_seed_outside_benchmarks(tmp_path):
    from testing_platform.autotest.apps.keepassxc_guest import GuestKeePassXC

    (tmp_path / 'benchmarks').mkdir()
    (tmp_path / 'secret.kdbx').write_bytes(b'x')
    guest = GuestKeePassXC(tmp_path)
    for bad in ('../secret.kdbx', 'missing.kdbx', ''):
        with pytest.raises(ValueError):
            guest.reset(bad, 'pw')
    with pytest.raises(RuntimeError):
        guest.launch()
    assert set(guest.handlers()) == {'kpxc_reset', 'kpxc_launch', 'kpxc_stop', 'kpxc_export', 'kpxc_config'}


def test_guest_ops_run_in_child_process_and_errors_come_back(tmp_path):
    from testing_platform.autotest.apps.keepassxc_guest import GuestKeePassXC

    (tmp_path / 'benchmarks').mkdir()
    handlers = GuestKeePassXC(tmp_path).handlers()
    with pytest.raises(RuntimeError, match='ValueError'):
        handlers['kpxc_reset']({'seed': '../x.kdbx', 'password': 'pw'})
    with pytest.raises(RuntimeError, match='kpxc_reset must be called first'):
        handlers['kpxc_config']({})


def test_guest_child_output_keeps_non_ascii_text(tmp_path):
    import json

    from testing_platform.autotest.apps.keepassxc_guest import GuestKeePassXC

    (tmp_path / 'run').mkdir()
    (tmp_path / 'run' / 'state.json').write_text(json.dumps({'seed': str(tmp_path / 's.kdbx'), 'password': 'pw'}),
                                                 encoding='utf-8')
    (tmp_path / 'KeePassXC' / 'config').mkdir(parents=True)
    text = '[GUI]\n网银=招商银行 工商银行\n'
    (tmp_path / 'KeePassXC' / 'config' / 'keepassxc.ini').write_text(text, encoding='utf-8')
    assert GuestKeePassXC(tmp_path).handlers()['kpxc_config']({}) == {'ini': text}


def test_guest_state_survives_between_instances(tmp_path, monkeypatch):
    from testing_platform.autotest.apps import keepassxc_guest

    monkeypatch.setattr(keepassxc_guest.KeePassXCEnv, 'reset', lambda self: {'stopped': []})
    (tmp_path / 'benchmarks' / 'm1').mkdir(parents=True)
    (tmp_path / 'benchmarks' / 'm1' / 'seed.kdbx').write_bytes(b'x')
    keepassxc_guest.GuestKeePassXC(tmp_path).reset('m1/seed.kdbx', 'pw')
    fresh = keepassxc_guest.GuestKeePassXC(tmp_path)
    env = fresh._need()
    assert env.password == 'pw' and env.seed_db.name == 'seed.kdbx'
    assert fresh.config() == {'ini': ''}


def test_guest_child_crash_and_timeout_become_runtime_errors(tmp_path, monkeypatch):
    import subprocess

    from testing_platform.autotest.apps import keepassxc_guest

    guest = keepassxc_guest.GuestKeePassXC(tmp_path)
    crashed = subprocess.CompletedProcess([], 3221225477, stdout='', stderr='access violation')
    monkeypatch.setattr(keepassxc_guest.subprocess, 'run', lambda *a, **k: crashed)
    with pytest.raises(RuntimeError, match='3221225477'):
        guest.run_isolated('kpxc_stop', {})

    def hang(*a, **k):
        raise subprocess.TimeoutExpired('python', 1)

    monkeypatch.setattr(keepassxc_guest.subprocess, 'run', hang)
    with pytest.raises(RuntimeError, match='timed out'):
        guest.run_isolated('kpxc_stop', {}, timeout=1)
    with pytest.raises(ValueError):
        guest.run_isolated('rm_rf', {})
