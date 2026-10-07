import os
import socket
import subprocess
import sys
import threading
import time

STATIC_TABLE: dict[int, str] = {
    1: ":method", 2: ":path", 3: ":status", 4: "host",
    5: "user-agent", 6: "accept", 7: "content-type",
    8: "content-length", 9: "server", 10: "date"
}

def make_frame(ftype: int, sid: int, payload: bytes) -> bytes:
    return len(payload).to_bytes(3, "big") + bytes([ftype, 0]) + sid.to_bytes(3, "big") + payload

def make_headers_payload(status: str, ctype: str) -> bytes:
    sb: bytes = status.encode("utf-8")
    cb: bytes = ctype.encode("utf-8")
    return bytes([0x83, len(sb)]) + sb + bytes([0x87, len(cb)]) + cb

def make_response(sid: int, status: str, ctype: str, body: bytes) -> bytes:
    hf: bytes = make_frame(2, sid, make_headers_payload(status, ctype))
    df: bytes = make_frame(1, sid, body)
    return hf + df

def read_exact(sock: socket.socket, n: int) -> bytes:
    buf: bytearray = bytearray()
    while len(buf) < n:
        chunk: bytes = sock.recv(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)

def decode_headers(b: bytes) -> dict[str, str] | None:
    hdrs: dict[str, str] = {}
    i: int = 0
    while i < len(b):
        ctrl: int = b[i]
        i += 1
        name: str = ""
        if ctrl == 0:
            if i >= len(b) or i + 1 + b[i] > len(b):
                return None
            name = b[i + 1 : i + 1 + b[i]].decode("utf-8", errors="replace")
            i += 1 + b[i]
        elif (ctrl & 0x80) != 0 and 1 <= (ctrl & 0x7F) <= 10:
            name = STATIC_TABLE[ctrl & 0x7F]
        else:
            return None
        if i >= len(b) or i + 1 + b[i] > len(b):
            return None
        hdrs[name] = b[i + 1 : i + 1 + b[i]].decode("utf-8", errors="replace")
        i += 1 + b[i]
    return hdrs

def read_request(sock: socket.socket) -> tuple[int, dict[str, str]] | None:
    hdr: bytes = read_exact(sock, 8)
    if len(hdr) < 8:
        return None
    length: int = int.from_bytes(hdr[0:3], "big")
    ftype: int = hdr[3]
    sid: int = int.from_bytes(hdr[5:8], "big")
    if ftype != 2:
        return None
    payload: bytes = read_exact(sock, length)
    if len(payload) < length:
        return None
    hdrs: dict[str, str] | None = decode_headers(payload)
    if hdrs is None:
        return None
    return sid, hdrs

def create_server_sock(port: int) -> socket.socket:
    s: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(5)
    return s

def run_case_ok(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req and req[1].get(":path") == "/index.html" and req[1].get(":method") == "GET" and "host" in req[1]:
            conn.sendall(make_response(req[0], "200", "text/html", b"<h1>ok</h1>\n"))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/index.html"], capture_output=True)
    t.join()
    return res.returncode == 0 and res.stdout == b"<h1>ok</h1>\n"

def run_case_notfound(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req and req[1].get(":path") == "/nope.html":
            conn.sendall(make_response(req[0], "404", "text/plain", b"not found\n"))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/nope.html"], capture_output=True)
    t.join()
    return res.returncode == 1 and res.stdout == b"not found\n"

def run_case_badreq(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req and req[1].get(":path") == "/x":
            conn.sendall(make_response(req[0], "400", "text/plain", b"bad request\n"))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/x"], capture_output=True)
    t.join()
    return res.returncode == 1 and res.stdout == b"bad request\n"

def run_case_srverr(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req and req[1].get(":path") == "/x":
            conn.sendall(make_response(req[0], "500", "text/plain", b"server error\n"))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/x"], capture_output=True)
    t.join()
    return res.returncode == 2 and res.stdout == b"server error\n"

def run_case_skip_before(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            unk: bytes = bytes.fromhex("00 00 03 42 00 00 00 01 DE AD BE")
            conn.sendall(unk + make_response(req[0], "200", "text/html", b"<h1>ok</h1>\n"))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/index.html"], capture_output=True)
    t.join()
    return res.returncode == 0 and res.stdout == b"<h1>ok</h1>\n"

def run_case_skip_mid(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            hf: bytes = make_frame(2, req[0], make_headers_payload("200", "text/html"))
            unk: bytes = bytes.fromhex("00 00 03 42 00 00 00 01 DE AD BE")
            df: bytes = make_frame(1, req[0], b"<h1>ok</h1>\n")
            conn.sendall(hf + unk + df)
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/index.html"], capture_output=True)
    t.join()
    return res.returncode == 0 and res.stdout == b"<h1>ok</h1>\n"

def run_case_err_frame(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            conn.sendall(bytes.fromhex("00 00 02 03 00 00 00 01 00 02"))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/index.html"], capture_output=True)
    t.join()
    return res.returncode == 3 and len(res.stderr) > 0

def run_case_data_first(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            df: bytes = make_frame(1, req[0], b"body")
            hf: bytes = make_frame(2, req[0], make_headers_payload("200", "text/html"))
            conn.sendall(df + hf)
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/index.html"], capture_output=True)
    t.join()
    return res.returncode == 3

def run_case_dup_headers(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            hf: bytes = make_frame(2, req[0], make_headers_payload("200", "text/html"))
            df: bytes = make_frame(1, req[0], b"body")
            conn.sendall(hf + hf + df)
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/index.html"], capture_output=True)
    t.join()
    return res.returncode == 3

def run_case_eof_early(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            hf: bytes = make_frame(2, req[0], make_headers_payload("200", "text/html"))
            conn.sendall(hf)
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/index.html"], capture_output=True)
    t.join()
    return res.returncode == 3

def run_case_empty_body(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            conn.sendall(make_response(req[0], "200", "text/plain", b""))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/empty.txt"], capture_output=True)
    t.join()
    return res.returncode == 0 and res.stdout == b""

def run_case_binary_body(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    expected: bytes = bytes(range(256))
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            conn.sendall(make_response(req[0], "200", "application/octet-stream", expected))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/bin"], capture_output=True)
    t.join()
    return res.returncode == 0 and res.stdout == expected

def run_case_multi3(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    server_ok: list[bool] = [True]
    def server_thread() -> None:
        conn, _ = s.accept()
        for expected_sid in (1, 2, 3):
            req: tuple[int, dict[str, str]] | None = read_request(conn)
            if not req or req[0] != expected_sid:
                server_ok[0] = False
                break
            conn.sendall(make_response(req[0], "200", "text/plain", b"part"))
        s.settimeout(0.2)
        try:
            extra_conn, _ = s.accept()
            extra_conn.close()
            server_ok[0] = False
        except (socket.timeout, OSError):
            pass
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([
        sys.executable, client_path,
        f"127.0.0.1:{port}/a", f"127.0.0.1:{port}/b", f"127.0.0.1:{port}/c"
    ], capture_output=True)
    t.join()
    return server_ok[0] and res.returncode == 0 and res.stdout == b"partpartpart"

def run_case_conn_refused(port: int) -> bool:
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    res = subprocess.run([sys.executable, client_path, f"127.0.0.1:{port}/index.html"], capture_output=True, text=True)
    has_msg: bool = len(res.stderr.strip()) > 0
    no_traceback: bool = "Traceback" not in res.stderr
    return res.returncode == 3 and has_msg and no_traceback

def run_case_v_flag(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            conn.sendall(make_response(req[0], "200", "text/html", b"<h1>ok</h1>\n"))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, "-v", f"127.0.0.1:{port}/index.html"], capture_output=True)
    t.join()
    stderr_txt: str = res.stderr.decode("utf-8", errors="replace")
    has_sent: bool = "» HEADERS" in stderr_txt
    has_rcv_h: bool = "« HEADERS" in stderr_txt
    has_rcv_d: bool = "« DATA" in stderr_txt
    return res.returncode == 0 and res.stdout == b"<h1>ok</h1>\n" and has_sent and has_rcv_h and has_rcv_d

def run_case_v_skip(port: int) -> bool:
    s: socket.socket = create_server_sock(port)
    client_path: str = os.path.join(os.path.dirname(__file__), "bcurl.py")
    def server_thread() -> None:
        conn, _ = s.accept()
        req: tuple[int, dict[str, str]] | None = read_request(conn)
        if req:
            unk: bytes = bytes.fromhex("00 00 03 42 00 00 00 01 DE AD BE")
            conn.sendall(unk + make_response(req[0], "200", "text/html", b"<h1>ok</h1>\n"))
        conn.close()
        s.close()
    t = threading.Thread(target=server_thread)
    t.start()
    res = subprocess.run([sys.executable, client_path, "-v", f"127.0.0.1:{port}/index.html"], capture_output=True)
    t.join()
    stderr_txt: str = res.stderr.decode("utf-8", errors="replace")
    has_unk: bool = "UNKNOWN(0x42)" in stderr_txt or "UNKNOWN" in stderr_txt
    return res.returncode == 0 and res.stdout == b"<h1>ok</h1>\n" and has_unk

CASES: dict[str, object] = {
    "ok": run_case_ok,
    "notfound": run_case_notfound,
    "badreq": run_case_badreq,
    "srverr": run_case_srverr,
    "skip_before": run_case_skip_before,
    "skip_mid": run_case_skip_mid,
    "err_frame": run_case_err_frame,
    "data_first": run_case_data_first,
    "dup_headers": run_case_dup_headers,
    "eof_early": run_case_eof_early,
    "empty_body": run_case_empty_body,
    "binary_body": run_case_binary_body,
    "multi3": run_case_multi3,
    "conn_refused": run_case_conn_refused,
    "v_flag": run_case_v_flag,
    "v_skip": run_case_v_skip,
}

def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: t2_rig.py PORT [CASE...]\n")
        sys.exit(1)
    port: int = int(sys.argv[1])
    selected: list[str] = sys.argv[2:] if len(sys.argv) > 2 else list(CASES.keys())
    failed: int = 0
    for name in selected:
        func = CASES.get(name)
        if not func:
            sys.stderr.write(f"unknown case: {name}\n")
            failed += 1
            continue
        try:
            ok: bool = bool(func(port))
        except Exception:
            ok = False
        if ok:
            sys.stdout.write(f"PASS {name}\n")
        else:
            sys.stdout.write(f"FAIL {name}\n")
            failed += 1
    if failed != 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
