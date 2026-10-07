import socket
import sys

TYPE_DATA: int = 1; TYPE_HEADERS: int = 2; TYPE_ERR: int = 3; TYPE_NAMES: dict[int, str] = {1: "DATA", 2: "HEADERS", 3: "ERR"}
STATIC_TABLE: dict[int, str] = {1: ":method", 2: ":path", 3: ":status", 4: "host", 5: "user-agent", 6: "accept", 7: "content-type", 8: "content-length", 9: "server", 10: "date"}

def read_exact(sock: socket.socket, n: int) -> bytes:
    buf: bytearray = bytearray()
    while len(buf) < n:
        chunk: bytes = sock.recv(n - len(buf))
        if not chunk: return b""
        buf.extend(chunk)
    return bytes(buf)

def dump_frame(d: str, ft: int, sid: int, p: bytes) -> None:
    tn: str = TYPE_NAMES.get(ft, f"UNKNOWN(0x{ft:02X})")
    f: bytes = len(p).to_bytes(3, "big") + bytes([ft, 0]) + sid.to_bytes(3, "big") + p
    sys.stderr.write(f"{d} {tn}  sid={sid} len={len(p)}\n")
    for off in range(0, len(f), 16):
        c: bytes = f[off : off + 16]
        hp, ap = [], []
        for b in c:
            hp.append(f"{b:02x}")
            ap.append(chr(b) if 32 <= b <= 126 else ".")
        sys.stderr.write(f"{off:08x}  {' '.join(hp[:8]):<23}  {' '.join(hp[8:]):<23}  |{''.join(ap)}|\n")

def decode_headers(b: bytes) -> dict[str, str]:
    hdrs: dict[str, str] = {}
    i: int = 0
    while i < len(b):
        ctrl: int = b[i]
        i += 1
        if ctrl == 0:
            if i >= len(b) or i + 1 + b[i] > len(b): return {}
            name: str = b[i + 1 : i + 1 + b[i]].decode("utf-8", errors="replace")
            i += 1 + b[i]
        elif (ctrl & 0x80) != 0 and 1 <= (ctrl & 0x7F) <= 10: name = STATIC_TABLE[ctrl & 0x7F]
        else: return {}
        if i >= len(b) or i + 1 + b[i] > len(b): return {}
        hdrs[name] = b[i + 1 : i + 1 + b[i]].decode("utf-8", errors="replace")
        i += 1 + b[i]
    return hdrs

def parse_url(url: str) -> tuple[str, int, str]:
    hp, path = url.split("/", 1) if "/" in url else (url, "")
    if ":" not in hp: sys.exit(3)
    h, p = hp.split(":", 1)
    return h, int(p), "/" + path

def make_req(sid: int, path: str, host: str, port: int) -> bytes:
    pb, hb = path.encode("utf-8"), f"{host}:{port}".encode("utf-8")
    p: bytes = bytes([0x81, 3]) + b"GET" + bytes([0x82, len(pb)]) + pb + bytes([0x84, len(hb)]) + hb
    return len(p).to_bytes(3, "big") + bytes([TYPE_HEADERS, 0]) + sid.to_bytes(3, "big") + p

def recv_response(sock: socket.socket, sid: int, verbose: bool) -> int:
    got_h, status = False, 0
    while True:
        hdr: bytes = read_exact(sock, 8)
        if len(hdr) < 8: sys.exit(3)
        length, ftype, rsid = int.from_bytes(hdr[0:3], "big"), hdr[3], int.from_bytes(hdr[5:8], "big")
        payload: bytes = read_exact(sock, length)
        if len(payload) < length or rsid != sid: sys.exit(3)
        if verbose: dump_frame("«", ftype, rsid, payload)
        if ftype == TYPE_ERR: sys.stderr.write(f"ERR {payload.hex()}\n"); sys.exit(3)
        if ftype == TYPE_HEADERS:
            if got_h: sys.exit(3)
            got_h, st = True, decode_headers(payload).get(":status", "")
            if len(st) != 3 or not st.isdigit(): sys.exit(3)
            status = int(st)
        elif ftype == TYPE_DATA:
            if not got_h: sys.exit(3)
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
            break
    return 0 if 200 <= status <= 299 else (2 if 500 <= status <= 599 else 1)

def main() -> None:
    sys.stderr.reconfigure(encoding="utf-8")
    args, verbose = sys.argv[1:], False
    if args and args[0] == "-v": verbose, args = True, args[1:]
    if not args: sys.exit(3)
    try:
        host, port, _ = parse_url(args[0])
        sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
    except (OSError, ValueError): sys.stderr.write("connect failed\n"); sys.exit(3)
    exit_code, sid = 0, 1
    try:
        for url in args:
            _, _, path = parse_url(url)
            req: bytes = make_req(sid, path, host, port)
            if verbose: dump_frame("»", TYPE_HEADERS, sid, req[8:])
            sock.sendall(req)
            exit_code = recv_response(sock, sid, verbose)
            sid += 1
    finally:
        sock.close()
    sys.exit(exit_code)

if __name__ == "__main__": main()
