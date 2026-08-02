"""Single-instance coordination -- a new file opened through Slate lands
as a TAB in one already-running window instead of spawning a new
process/window per file.

Plain TCP loopback socket, not a lock file + OS-specific IPC (named
pipe/D-Bus) -- cross-platform without per-OS code, and works identically
in dev (Linux) and deployment (Windows). Bound to 127.0.0.1 only --
never reachable off-machine.
"""
import queue
import socket
import threading

PORT = 51234  # arbitrary, fixed -- client-probe and server must agree.


def try_send_to_running_instance(path: str, port: int = PORT, timeout: float = 0.3) -> bool:
    """Returns True if an instance was already listening and the path
    was handed off to it (caller should NOT open its own window).
    False means no instance is running -- caller becomes the server."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.sendall((path + "\n").encode("utf-8"))
        return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def start_server(on_path, port: int = PORT):
    """Starts a background thread listening for paths from later
    invocations. on_path(path) is called for each one -- the caller
    (slate.py) is responsible for making on_path thread-safe (route
    through root.after()); direct Tk calls from a non-main thread are
    not safe.

    Returns the queue paths are placed on AND the server socket, so a
    caller that wants on_path to be a plain queue.put can just pass
    that in directly instead of writing a wrapper."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(5)

    def serve():
        while True:
            try:
                conn, _addr = server.accept()
            except OSError:
                return  # socket closed (shutdown) -- exit cleanly
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                path = data.decode("utf-8").strip()
                if path:
                    on_path(path)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return server


def make_ipc_queue():
    """Convenience: a queue.Queue plus a ready-to-pass on_path callable
    for the common case (server just wants to hand paths to the main
    thread via polling, not run arbitrary logic per path)."""
    q = queue.Queue()
    return q, q.put
