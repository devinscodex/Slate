import queue
import time

import singleinstance


def _free_port():
    """A distinct port per test run so parallel/rapid test runs never
    collide on a still-closing socket from a prior test."""
    import socket
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


def test_path_with_no_trailing_newline_from_client_still_delivered_on_disconnect():
    """The server reads until a newline OR the connection closes --
    try_send_to_running_instance always sends one, but this guards the
    protocol itself against a future caller that doesn't."""
    import socket
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
