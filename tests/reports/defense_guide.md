# BCURLP/1 Oral Defense Guide (Tier 3)

Concise, one-sentence oral defenses for each of the eight graded design points.

---

### 1. `read_exact` — Why `recv(n)` alone is a bug
> **One-Sentence Defense**: TCP is a streaming byte protocol with no message boundaries; `recv(n)` returns *up to* `n` bytes as IP packets fragment, so a loop accumulating bytes until `len(buf) == n` or EOF is mandatory to prevent corrupted frame headers.

---

### 2. The 8-Byte Header Parse — `int.from_bytes(..., "big")` and Why Big-Endian
> **One-Sentence Defense**: Internet standard protocols use big-endian (network byte order, most significant byte first) across all multi-byte integers, and Python's `int.from_bytes(..., "big")` directly parses arbitrary 24-bit widths without awkward 3-byte C struct padding.

---

### 3. The Skip Rule — Where Unknown TYPE Reads LENGTH Bytes and Continues
> **One-Sentence Defense**: Located in the frame dispatch loop, when `ftype != TYPE_HEADERS` (and not `ERR`), the receiver reads exactly `length` payload bytes from the socket and discards them with `continue`, preserving perfect stream byte-synchronization for forward compatibility with version 2 frame types.

---

### 4. The Header-Block Decode — What `0x81`/`0x82`/`0x84` Mean and the `|0x80` Trick
> **One-Sentence Defense**: Borrowing HPACK's indexed representation, setting the high bit (`0x80 | index`) signals a 1-byte lookup in the Static Table (`0x81` is `:method`, `0x82` is `:path`, `0x84` is `host`), which distinguishes indexed names in one comparison from literal names (`0x00`).

---

### 5. Path Containment — `realpath` + `commonpath`, and Why `startswith` is a Security Hole
> **One-Sentence Defense**: `os.path.commonpath([root_real, full_real]) == root_real` verifies that the canonical resolved path strictly resides within the root directory tree, whereas string `startswith` creates a directory traversal vulnerability by incorrectly matching sibling prefixes like `/www-secret` against `/www`.

---

### 6. The Keep-Alive Loop — Where It Goes Back to `read_exact(8)`
> **One-Sentence Defense**: In `bserve.py`'s `serve_connection`, after `sock.sendall` emits the complete response, execution stays inside `while True` and loops directly back to `read_exact(sock, 8)` without closing the socket, closing only when the client disconnects (EOF) or sends an ERR frame.

---

### 7. The Client State Machine — HEADERS → DATA, and Exit 3
> **One-Sentence Defense**: The client strictly transitions through a deterministic sequence (`HEADERS` first, then optional unknown frames skipped, then `DATA`), and immediately terminates with exit code 3 if frames arrive out of order (DATA before HEADERS), if duplicate HEADERS arrive, or if EOF occurs mid-stream.

---

### 8. Exit-Code Mapping — `:status` String → 0 / 1 / 2 / 3
> **One-Sentence Defense**: The client parses the 3-character ASCII status string and maps HTTP response status classes directly to UNIX exit codes: `2xx` maps to `0`, `4xx` maps to `1`, `5xx` maps to `2`, and connection failures or wire protocol errors trigger `3`.
