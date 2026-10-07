import hashlib, pathlib, re, socket, subprocess, sys, time

PORT = 9077
HOSTSTR = f"localhost:{PORT}"
RESULTS = []

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent

def check(name, cond, detail=""):
    RESULTS.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not cond else ""))

def read_exact(sock, count):
    chunks = b""
    while len(chunks) < count:
        part = sock.recv(count - len(chunks))
        if not part:
            raise ConnectionError("eof")
        chunks = chunks + part
    return chunks

def request_frame(sid, path, host):
    block = bytes([0x81, 0x03]) + b"GET"
    block = block + bytes([0x82, len(path)]) + path.encode()
    block = block + bytes([0x84, len(host)]) + host.encode()
    header = len(block).to_bytes(3, "big") + bytes([0x02, 0x00]) + sid.to_bytes(3, "big")
    return header + block

def response_200(sid):
    head = (16).to_bytes(3, "big") + bytes([0x02, 0x00]) + sid.to_bytes(3, "big")
    head = head + bytes.fromhex("83 03 32 30 30 87 09 74 65 78 74 2F 68 74 6D 6C")
    data = (12).to_bytes(3, "big") + bytes([0x01, 0x00]) + sid.to_bytes(3, "big") + b"<h1>ok</h1>\n"
    return head + data

def run_bcurl(args):
    return subprocess.run([sys.executable, str(ROOT_DIR / "bcurl.py")] + args, capture_output=True, timeout=30, cwd=str(ROOT_DIR))

BANNED = re.compile(r"(?i)\b(todo|fixme|hack|xxx|claude|chatgpt|copilot|gpt|gemini|openai|anthropic|generated|assisted)\b")
COMMENT = re.compile(r"^\s*#|\"\"\"|'''")

nl_serve = len((ROOT_DIR / "bserve.py").read_text().splitlines())
nl_curl = len((ROOT_DIR / "bcurl.py").read_text().splitlines())
check(f"bserve.py <= 100 LOC (got {nl_serve})", nl_serve <= 100)
check(f"bcurl.py <= 100 LOC (got {nl_curl})", nl_curl <= 100)

hits = []
for fname in ["bserve.py", "bcurl.py", "specs.md", "hexdump_annotated.txt"]:
    text = (ROOT_DIR / fname).read_text(errors="replace")
    for line_no, line in enumerate(text.splitlines(), 1):
        if BANNED.search(line) or (fname.endswith(".py") and COMMENT.search(line)):
            hits.append(f"{fname}:{line_no}")
check("no banned markers / comments / docstrings in hand-in set", not hits, "; ".join(hits[:3]))

check("index.html is exactly 12 bytes", (ROOT_DIR / "www/index.html").stat().st_size == 12)
check("empty.txt is 0 bytes", (ROOT_DIR / "www/empty.txt").stat().st_size == 0)
check("big.bin is exactly 1 MiB", (ROOT_DIR / "www/big.bin").stat().st_size == 1048576)

serv_out_path = ROOT_DIR / "server_stdout.tmp"
serv_out = open(serv_out_path, "wb")
proc = subprocess.Popen([sys.executable, str(ROOT_DIR / "bserve.py"), str(ROOT_DIR / "www"), str(PORT)], stdout=serv_out, stderr=subprocess.DEVNULL, cwd=str(ROOT_DIR))
try:
    up = False
    deadline = time.time() + 4
    while time.time() < deadline and not up:
        probe = socket.socket()
        up = probe.connect_ex(("127.0.0.1", PORT)) == 0
        probe.close()
        if not up:
            time.sleep(0.05)
    if not up:
        print("[FAIL] server did not start"); sys.exit(1)

    r = run_bcurl([f"localhost:{PORT}/index.html"])
    check("200: body exact + exit 0", r.returncode == 0 and r.stdout == b"<h1>ok</h1>\n", repr(r.stdout))
    r = run_bcurl([f"localhost:{PORT}/nope.html"])
    check("404: body still printed + exit 1", r.returncode == 1 and r.stdout == b"not found\n")
    r = run_bcurl([f"localhost:{PORT}/../etc/passwd"])
    check("traversal: 400 + exit 1", r.returncode == 1 and r.stdout == b"bad request\n")
    r = run_bcurl([f"localhost:{PORT}/index.html", f"localhost:{PORT}/empty.txt", f"localhost:{PORT}/index.html"])
    check("3 URLs one invocation: bodies concatenated + exit 0", r.returncode == 0 and r.stdout == b"<h1>ok</h1>\n" * 2)

    r = run_bcurl(["-v", f"localhost:{PORT}/index.html"])
    check("-v: stdout stays pure body bytes", r.stdout == b"<h1>ok</h1>\n")
    check("-v: hexdump on stderr with type labels", b"HEADERS" in r.stderr and b"DATA" in r.stderr)

    big = run_bcurl([f"localhost:{PORT}/big.bin"])
    check("big.bin: byte-exact 1 MiB transfer", hashlib.sha256(big.stdout).digest() == hashlib.sha256((ROOT_DIR / "www/big.bin").read_bytes()).digest())

    sock = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    sock.settimeout(5)
    sock.sendall(bytes.fromhex("00 00 03 42 00 00 00 01 DE AD BE"))
    sock.sendall(request_frame(1, "/index.html", HOSTSTR))
    check("skip rule: unknown 0x42 skipped, response clean", read_exact(sock, 44) == response_200(1))
    sock.sendall(request_frame(2, "/index.html", HOSTSTR))
    check("keep-alive: second request sid 2 after skip", read_exact(sock, 44) == response_200(2))
    sock.sendall(bytes.fromhex("00 00 02 03 00 00 00 01 00 01"))
    check("ERR frame closes connection", sock.recv(1) == b"")
    sock.close()

    def hexdump_lines(raw):
        out = []
        for line in raw.decode("utf-8", "replace").splitlines():
            if re.match(r"^[0-9a-fA-F]{8}  ", line):
                out.append(line.strip())
        return out

    ann = (ROOT_DIR / "hexdump_annotated.txt").read_text(errors="replace")
    live = hexdump_lines(r.stderr)
    missing = []
    for hl in live:
        if hl not in ann:
            missing.append(hl)
    check(f"annotated hexdump contains the real live bytes ({len(live)} hex lines checked)", len(live) > 0 and not missing, "; ".join(missing[:2]))
    up_ann = "LENGTH" in ann.upper() and "TYPE" in ann.upper() and "STREAM" in ann.upper()
    check("annotated hexdump has real annotations", up_ann)
finally:
    proc.terminate()
    proc.wait()
    serv_out.close()

time.sleep(0.3)
r = run_bcurl([f"localhost:{PORT}/index.html"])
check("connection refused: exit 3, clean", r.returncode == 3)
check("server stdout stayed empty (purity)", serv_out_path.stat().st_size == 0)
serv_out_path.unlink()

passed = 0
for c in RESULTS:
    if c:
        passed = passed + 1
print(f"\n{passed}/{len(RESULTS)} checks passed")
sys.exit(0 if passed == len(RESULTS) else 1)
