import os
import socket
import sys

TYPE_DATA: int = 1
TYPE_HEADERS: int = 2
TYPE_ERR: int = 3
STATIC_TABLE: dict[int, str] = {1: ":method", 2: ":path", 3: ":status", 4: "host", 5: "user-agent", 6: "accept", 7: "content-type", 8: "content-length", 9: "server", 10: "date"}
MIMES: dict[str, str] = {".html": "text/html", ".htm": "text/html", ".txt": "text/plain", ".css": "text/css", ".js": "text/javascript", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

def read_exact(sock: socket.socket, n: int) -> bytes:
    buf: bytearray = bytearray()
    while len(buf) < n:
        chunk: bytes = sock.recv(n - len(buf))
        if not chunk: return b""
        buf.extend(chunk)
    return bytes(buf)

def decode_headers(b: bytes) -> dict[str, str] | None:
    hdrs: dict[str, str] = {}
    i: int = 0
    while i < len(b):
        ctrl: int = b[i]
        i += 1
        if ctrl == 0:
            if i >= len(b) or i + 1 + b[i] > len(b): return None
            name: str = b[i + 1 : i + 1 + b[i]].decode("utf-8", errors="replace")
            i += 1 + b[i]
        elif (ctrl & 0x80) != 0 and 1 <= (ctrl & 0x7F) <= 10:
            name = STATIC_TABLE[ctrl & 0x7F]
        else:
            return None
        if i >= len(b) or i + 1 + b[i] > len(b): return None
        hdrs[name] = b[i + 1 : i + 1 + b[i]].decode("utf-8", errors="replace")
        i += 1 + b[i]
    return hdrs

def encode_response(sid: int, status: str, ctype: str, body: bytes) -> bytes:
    sb, cb = status.encode("utf-8"), ctype.encode("utf-8")
    hp: bytes = bytes([0x83, len(sb)]) + sb + bytes([0x87, len(cb)]) + cb
    hf: bytes = len(hp).to_bytes(3, "big") + bytes([TYPE_HEADERS, 0]) + sid.to_bytes(3, "big") + hp
    df: bytes = len(body).to_bytes(3, "big") + bytes([TYPE_DATA, 0]) + sid.to_bytes(3, "big") + body
    return hf + df

def resolve_request(root_dir: str, hdrs: dict[str, str] | None) -> tuple[str, str, bytes]:
    if hdrs is None or hdrs.get(":method") != "GET" or not hdrs.get(":path", "").startswith("/") or "host" not in hdrs:
        return "400", "text/plain", b"bad request\n"
    rp: str = hdrs[":path"]
    if rp == "/": rp = "/index.html"
    fp: str = os.path.realpath(os.path.join(root_dir, rp.lstrip("/")))
    if os.path.commonpath([root_dir, fp]) != root_dir: return "400", "text/plain", b"bad request\n"
    if not os.path.exists(fp) or os.path.isdir(fp): return "404", "text/plain", b"not found\n"
    try:
        if os.path.getsize(fp) > 16777215: return "500", "text/plain", b"server error\n"
        with open(fp, "rb") as f: data: bytes = f.read()
        return "200", MIMES.get(os.path.splitext(fp)[1].lower(), "application/octet-stream"), data
    except OSError:
        return "500", "text/plain", b"server error\n"

def serve_connection(sock: socket.socket, root_dir: str) -> None:
    debug: bool = os.environ.get("BSERVE_DEBUG") == "1"
    while True:
        hdr: bytes = read_exact(sock, 8)
        if len(hdr) < 8: break
        length, ftype, sid = int.from_bytes(hdr[0:3], "big"), hdr[3], int.from_bytes(hdr[5:8], "big")
        payload: bytes = read_exact(sock, length)
        if len(payload) < length or ftype == TYPE_ERR: break
        if debug: sys.stderr.write(f"frame: type={ftype} sid={sid} len={length}\n")
        if ftype != TYPE_HEADERS: continue
        status, ctype, body = resolve_request(root_dir, decode_headers(payload))
        sock.sendall(encode_response(sid, status, ctype, body))

def main() -> None:
    if len(sys.argv) < 3: sys.exit(1)
    root_dir: str = os.path.realpath(sys.argv[1])
    server_sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("0.0.0.0", int(sys.argv[2])))
    server_sock.listen()
    try:
        while True:
            client_sock, _ = server_sock.accept()
            try:
                serve_connection(client_sock, root_dir)
            except OSError:
                pass
            finally:
                client_sock.close()
    except KeyboardInterrupt:
        pass
    finally:
        server_sock.close()

if __name__ == "__main__":
    main()
