import sys
import socket

VECTOR_A: bytes = bytes.fromhex(
    "00 00 22 02 00 00 00 01"
    "81 03 47 45 54"
    "82 0B 2F 69 6E 64 65 78 2E 68 74 6D 6C"
    "84 0E 6C 6F 63 61 6C 68 6F 73 74 3A 39 30 30 30"
)

VECTOR_B: bytes = bytes.fromhex(
    "00 00 10 02 00 00 00 01"
    "83 03 32 30 30"
    "87 09 74 65 78 74 2F 68 74 6D 6C"
    "00 00 0C 01 00 00 00 01"
    "3C 68 31 3E 6F 6B 3C 2F 68 31 3E 0A"
)

VECTOR_C: bytes = bytes.fromhex(
    "00 00 11 02 00 00 00 01"
    "83 03 34 30 34"
    "87 0A 74 65 78 74 2F 70 6C 61 69 6E"
    "00 00 0A 01 00 00 00 01"
    "6E 6F 74 20 66 6F 75 6E 64 0A"
)

VECTOR_D: bytes = bytes.fromhex(
    "00 00 11 02 00 00 00 01"
    "83 03 34 30 30"
    "87 0A 74 65 78 74 2F 70 6C 61 69 6E"
    "00 00 0C 01 00 00 00 01"
    "62 61 64 20 72 65 71 75 65 73 74 0A"
)

def set_stream_id(frame: bytes, sid: int) -> bytes:
    sid_bytes: bytes = sid.to_bytes(3, "big")
    return frame[:5] + sid_bytes + frame[8:]

def set_response_sid(resp: bytes, sid: int) -> bytes:
    h_len: int = int.from_bytes(resp[0:3], "big")
    first_frame: bytes = set_stream_id(resp[: 8 + h_len], sid)
    second_frame: bytes = set_stream_id(resp[8 + h_len :], sid)
    return first_frame + second_frame

def read_exact(sock: socket.socket, count: int) -> bytes:
    buf: bytearray = bytearray()
    while len(buf) < count:
        chunk: bytes = sock.recv(count - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)

def drain_socket(sock: socket.socket) -> bytes:
    sock.settimeout(0.1)
    extra: bytes = b""
    try:
        extra = sock.recv(4096)
    except (socket.timeout, OSError):
        pass
    return extra

def connect(port: int) -> socket.socket:
    sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    sock.connect(("127.0.0.1", port))
    return sock

def run_case_ok(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        sock.sendall(VECTOR_A)
        resp: bytes = read_exact(sock, len(VECTOR_B))
        if resp != VECTOR_B:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_ok_sid7(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = set_stream_id(VECTOR_A, 7)
        expected: bytes = set_response_sid(VECTOR_B, 7)
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(expected))
        if resp != expected:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_root_rewrite(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex(
            "00 00 18 02 00 00 00 01"
            "81 03 47 45 54"
            "82 01 2F"
            "84 0E 6C 6F 63 61 6C 68 6F 73 74 3A 39 30 30 30"
        )
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_B))
        if resp != VECTOR_B:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_404(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex(
            "00 00 21 02 00 00 00 01"
            "81 03 47 45 54"
            "82 0A 2F 6E 6F 70 65 2E 68 74 6D 6C"
            "84 0E 6C 6F 63 61 6C 68 6F 73 74 3A 39 30 30 30"
        )
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_C))
        if resp != VECTOR_C:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_dir_404(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex(
            "00 00 1E 02 00 00 00 01"
            "81 03 47 45 54"
            "82 07 2F 73 75 62 64 69 72"
            "84 0E 6C 6F 63 61 6C 68 6F 73 74 3A 39 30 30 30"
        )
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_C))
        if resp != VECTOR_C:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_traversal(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex(
            "00 00 25 02 00 00 00 01"
            "81 03 47 45 54"
            "82 0E 2F 2E 2E 2F 65 74 63 2F 70 61 73 73 77 64"
            "84 0E 6C 6F 63 61 6C 68 6F 73 74 3A 39 30 30 30"
        )
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_D))
        if resp != VECTOR_D:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_malformed_idx0(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex("00 00 01 02 00 00 00 01 80")
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_D))
        if resp != VECTOR_D:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_malformed_rsv(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex("00 00 05 02 00 00 00 01 8B 03 41 42 43")
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_D))
        if resp != VECTOR_D:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_malformed_ctrl(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex("00 00 01 02 00 00 00 01 05")
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_D))
        if resp != VECTOR_D:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_missing_path(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex("00 00 05 02 00 00 00 01 81 03 47 45 54")
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_D))
        if resp != VECTOR_D:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_method_post(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex(
            "00 00 23 02 00 00 00 01"
            "81 04 50 4F 53 54"
            "82 0B 2F 69 6E 64 65 78 2E 68 74 6D 6C"
            "84 0E 6C 6F 63 61 6C 68 6F 73 74 3A 39 30 30 30"
        )
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_D))
        if resp != VECTOR_D:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_literal_ok(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = (
            bytes.fromhex("00 00 36 02 00 00 00 01")
            + VECTOR_A[8:]
            + bytes.fromhex("00 0A 75 73 65 72 2D 61 67 65 6E 74 07 62 63 75 72 6C 2F 31")
        )
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_B))
        if resp != VECTOR_B:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_unknown_hdr(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = (
            bytes.fromhex("00 00 2B 02 00 00 00 01")
            + VECTOR_A[8:]
            + bytes.fromhex("00 03 66 6F 6F 03 62 61 72")
        )
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(VECTOR_B))
        if resp != VECTOR_B:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_skip_unknown(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        unknown_frame: bytes = bytes.fromhex("00 00 03 42 00 00 00 01 DE AD BE")
        sock.sendall(unknown_frame + VECTOR_A)
        resp: bytes = read_exact(sock, len(VECTOR_B))
        if resp != VECTOR_B:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_skip_data(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        data_frame: bytes = bytes.fromhex("00 00 02 01 00 00 00 01 CA FE")
        sock.sendall(data_frame + VECTOR_A)
        resp: bytes = read_exact(sock, len(VECTOR_B))
        if resp != VECTOR_B:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_keepalive3(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        for sid in (1, 2, 3):
            req: bytes = set_stream_id(VECTOR_A, sid)
            expected: bytes = set_response_sid(VECTOR_B, sid)
            sock.sendall(req)
            resp: bytes = read_exact(sock, len(expected))
            if resp != expected:
                return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_empty_file(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex(
            "00 00 21 02 00 00 00 01"
            "81 03 47 45 54"
            "82 0A 2F 65 6D 70 74 79 2E 74 78 74"
            "84 0E 6C 6F 63 61 6C 68 6F 73 74 3A 39 30 30 30"
        )
        expected: bytes = bytes.fromhex(
            "00 00 11 02 00 00 00 01"
            "83 03 32 30 30"
            "87 0A 74 65 78 74 2F 70 6C 61 69 6E"
            "00 00 00 01 00 00 00 01"
        )
        sock.sendall(req)
        resp: bytes = read_exact(sock, len(expected))
        if resp != expected:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_big(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        req: bytes = bytes.fromhex(
            "00 00 1F 02 00 00 00 01"
            "81 03 47 45 54"
            "82 08 2F 62 69 67 2E 62 69 6E"
            "84 0E 6C 6F 63 61 6C 68 6F 73 74 3A 39 30 30 30"
        )
        sock.sendall(req)
        hdr_frame: bytes = read_exact(sock, 8 + 0x1F)
        expected_hdr: bytes = bytes.fromhex(
            "00 00 1F 02 00 00 00 01"
            "83 03 32 30 30"
            "87 18 61 70 70 6C 69 63 61 74 69 6F 6E 2F 6F 63 74 65 74 2D 73 74 72 65 61 6D"
        )
        if hdr_frame != expected_hdr:
            return False
        data_hdr: bytes = read_exact(sock, 8)
        expected_data_hdr: bytes = bytes.fromhex("10 00 00 01 00 00 00 01")
        if data_hdr != expected_data_hdr:
            return False
        data_body: bytes = read_exact(sock, 1048576)
        expected_data_body: bytes = bytes(bytearray(i % 256 for i in range(1048576)))
        if data_body != expected_data_body:
            return False
        if drain_socket(sock) != b"":
            return False
        return True
    finally:
        sock.close()

def run_case_err_closes(port: int) -> bool:
    sock: socket.socket = connect(port)
    try:
        err_frame: bytes = bytes.fromhex("00 00 02 03 00 00 00 01 00 01")
        sock.sendall(err_frame)
        rem: bytes = sock.recv(16)
        if rem != b"":
            return False
        return True
    finally:
        sock.close()

CASES: dict[str, object] = {
    "ok": run_case_ok,
    "ok_sid7": run_case_ok_sid7,
    "root_rewrite": run_case_root_rewrite,
    "404": run_case_404,
    "dir_404": run_case_dir_404,
    "traversal": run_case_traversal,
    "malformed_idx0": run_case_malformed_idx0,
    "malformed_rsv": run_case_malformed_rsv,
    "malformed_ctrl": run_case_malformed_ctrl,
    "missing_path": run_case_missing_path,
    "method_post": run_case_method_post,
    "literal_ok": run_case_literal_ok,
    "unknown_hdr": run_case_unknown_hdr,
    "skip_unknown": run_case_skip_unknown,
    "skip_data": run_case_skip_data,
    "keepalive3": run_case_keepalive3,
    "empty_file": run_case_empty_file,
    "big": run_case_big,
    "err_closes": run_case_err_closes,
}

def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: t1_rig.py PORT [CASE...]\n")
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
