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
