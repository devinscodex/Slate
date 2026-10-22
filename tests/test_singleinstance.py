import socket
import sys
import time

import pytest

import singleinstance


def _free_port():
    """A distinct port per test run so parallel/rapid test runs never
    collide on a still-closing socket from a prior test."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_no_server_running_returns_false():
    port = _free_port()
    assert singleinstance.try_send_to_running_instance("/tmp/x.pdf", port=port, timeout=0.2) is False


def test_server_receives_a_sent_path():
    port = _free_port()
    q, on_path = singleinstance.make_ipc_queue()
    server = singleinstance.start_server(on_path, port=port)
    try:
        sent = singleinstance.try_send_to_running_instance("/some/real/report.pdf", port=port)
        assert sent is True
        received = q.get(timeout=2)
        assert received == "/some/real/report.pdf"
    finally:
        server.close()


def test_server_receives_multiple_paths_in_order():
    port = _free_port()
    q, on_path = singleinstance.make_ipc_queue()
    server = singleinstance.start_server(on_path, port=port)
    try:
        for p in ["/a.pdf", "/b.html", "/c.png"]:
            assert singleinstance.try_send_to_running_instance(p, port=port) is True
        results = [q.get(timeout=2) for _ in range(3)]
        assert results == ["/a.pdf", "/b.html", "/c.png"]
    finally:
        server.close()


def test_losing_the_bind_is_a_reliable_signal_a_server_exists():
    """Regression for the real Explorer multi-select race: launching
    several processes near-simultaneously means each one's probe can
    see 'nobody's listening yet' before ANY of them has started
    serving. The fix binds first -- this proves the bind loss itself
    (not a separate probe) is what a second process must react to."""
    port = _free_port()
    q, on_path = singleinstance.make_ipc_queue()
    server = singleinstance.start_server(on_path, port=port)
    try:
        second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(OSError):
            second.bind(("127.0.0.1", port))
        second.close()
        # The process that lost the bind retries the handoff against
        # the winner -- same path a real second main() takes.
        assert singleinstance.try_send_to_running_instance("/handed/off.pdf", port=port) is True
        assert q.get(timeout=2) == "/handed/off.pdf"
    finally:
        server.close()


def test_reuseaddr_not_set_on_windows(monkeypatch):
    """Real incident: Windows' SO_REUSEADDR lets an unrelated process
    bind the exact same (address, port) a socket is already actively
    listening on, no error raised -- the opposite of POSIX's narrower
    TIME_WAIT-rebind semantics. Slate 1.7.6 opened 3 separate windows
    for 3 near-simultaneous real-Windows launches because every one of
    them succeeded at bind(). Must stay off on win32."""
    monkeypatch.setattr(sys, "platform", "win32")
    port = _free_port()
    server = singleinstance.start_server(lambda p: None, port=port)
    try:
        assert server.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
    finally:
        server.close()


def test_reuseaddr_set_on_posix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    port = _free_port()
    server = singleinstance.start_server(lambda p: None, port=port)
    try:
        assert server.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) != 0
    finally:
        server.close()


def test_path_with_no_trailing_newline_from_client_still_delivered_on_disconnect():
    """The server reads until a newline OR the connection closes --
    try_send_to_running_instance always sends one, but this guards the
    protocol itself against a future caller that doesn't."""
    port = _free_port()
    q, on_path = singleinstance.make_ipc_queue()
    server = singleinstance.start_server(on_path, port=port)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
            s.sendall(b"/no/newline/here.pdf")
        # connection closes on with-block exit -- recv returns b"" next,
        # loop breaks, whatever arrived (even without \n) should still
        # have been captured up to that point
        time.sleep(0.3)
        assert q.get(timeout=2) == "/no/newline/here.pdf"
    finally:
        server.close()
