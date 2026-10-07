# specs.md — BCURLP/1: Binary Curl Protocol, version 1

Single source of truth for every byte on the wire. A stranger must be able to implement a
compatible peer from this document alone.

## §1 Model

- Transport: one TCP connection. No TLS. No connection preface — the first
  octet on the wire is frame-header byte 0.
- A **request** is exactly one HEADERS frame, client → server.
- A **response** is exactly one HEADERS frame followed by exactly one DATA
  frame, server → client, both on the request's stream id. The DATA frame
  may be zero-length.
- A **stream** is one request/response pair. The client picks stream ids
  1, 2, 3, … incrementing per request. The server echoes the id.
- Strictly sequential: the client sends request N+1 only after response N
  is complete. No multiplexing, no pipelining in v1.
- All integers on the wire are UNSIGNED, BIG-ENDIAN (network byte order).

## §2 Frame header — fixed 8 bytes, every frame

    byte 0–2   LENGTH     24 bits   payload length, 0 .. 16,777,215
    byte 3     TYPE        8 bits   see §3
    byte 4     FLAGS       8 bits   0x00 in v1 (see §2.1)
    byte 5–7   STREAM_ID  24 bits   0 .. 16,777,215

Reads are exact: a receiver blocks until LENGTH payload bytes arrive or
the connection closes. EOF mid-frame is unrecoverable → close.

### §2.1 Why these widths (defense)
- **LENGTH 24**: caps a corrupt/malicious length at 16 MB — bounded memory
  before validation, and matches HTTP/2's default max frame payload. Any
  course-sized file fits.
- **TYPE 8**: 256 types is far more than v1 needs; the payoff is the skip
  rule (§3), which is what leaves room for a version 2.
- **FLAGS 8**: unused in v1, but flags are the cheapest possible extension
  hook (FIN, END_HEADERS in v2) — 1 byte per frame buys forward
  compatibility without a version bump. Senders send 0x00; receivers MUST
  accept any value and treat it as 0x00.
- **STREAM_ID 24**: v1 is sequential so even 8 bits would do; 24 mirrors
  HTTP/2's stream-id spirit (minus its reserved bit) and leaves headroom
  for v2 multiplexing. 3+1+1+3 makes the header exactly 8 bytes — one
  aligned word, trivial to hexdump.

## §3 Frame types

| TYPE | Name    | Payload                                     |
|------|---------|---------------------------------------------|
| 0x01 | DATA    | raw body bytes                              |
| 0x02 | HEADERS | header block per §4                         |
| 0x03 | ERR     | 2-byte code: 0x0001 INTERNAL, 0x0002 PROTOCOL |
| any  | unknown | —                                           |

**THE SKIP RULE (may not be violated):** a receiver that meets a frame
type it does not know MUST skip it cleanly — read the 8-byte header, read
and discard exactly LENGTH payload bytes, continue with the next frame.
Never crash, never close, never lose byte-sync.

Additional rules:
- On the server, ONLY a HEADERS frame triggers a response. Every other
  frame — known or unknown — is skipped per the skip rule.
- On the client, a response is HEADERS then DATA. Unknown types arriving
  mid-response are skipped. An ERR frame at any point → print the code to
  stderr, exit 3 (§7).
- Response shape violations (DATA before HEADERS, HEADERS twice, extra
  frames after DATA) → protocol error, exit 3 (client) / close (server).

## §4 Header block encoding (HPACK's first two mechanisms)

A header block is a sequence of entries filling the payload exactly.

**String** = 1 length byte (0–255) + that many UTF-8 bytes. (255 bytes is
plenty for paths and header values in v1.)

**Entry**, keyed on its first control byte:
- `0x80 | i`  → **indexed name**: name = static table entry *i* (§4.1),
                followed by one String (the value).
- `0x00`      → **literal**: one String (name) + one String (value).
- anything else (0x01–0x7F, or 0x80 with index 0) → malformed → 400.

Index values 11–127 are reserved: receiving one is malformed → 400.
Sending a known name literally is legal. Receivers MUST ignore header
entries whose name they do not know (forward compat at the header level).

### §4.1 Static table — the ten names we actually send

| Index | Name            | Used in |
|-------|-----------------|---------|
| 1     | `:method`       | request (required) |
| 2     | `:path`         | request (required) |
| 3     | `:status`       | response (required) |
| 4     | `host`          | request (required) |
| 5     | `user-agent`    | either (optional) |
| 6     | `accept`        | either (optional) |
| 7     | `content-type`  | response (required) |
| 8     | `content-length`| unused in v1 (frame LENGTH carries body size) |
| 9     | `server`        | response (optional) |
| 10    | `date`          | response (optional) |

Pseudo-headers first (mirrors HTTP/2), then request-frequency order.

## §5 HTTP semantics

**Requests.** Required entries: `:method` = `GET` (exactly, case-sensitive),
`:path` (must begin with `/`), `host` (presence required, value unchecked —
no vhosts in v1). Anything else is optional and ignored. Violations → 400.

**Path rules (server).**
- Use `:path` verbatim, relative to the server's document root. No
  %-decoding, no query strings in v1.
- `:path` = `/` is rewritten to `/index.html`.
- Resolve the real path; if it escapes the root (e.g. `../`) → **400**.
- Missing file, or a directory other than `/` → **404**.

**Responses.** Required entries: `:status`, `content-type`. Body rules:

| :status | when | DATA body | content-type |
|---------|------|-----------|--------------|
| 200 | file read OK | file bytes | by extension, below |
| 400 | malformed request (bad block, bad index, missing/invalid required headers, path escape) | `bad request\n` | `text/plain` |
| 404 | file/dir not found | `not found\n` | `text/plain` |
| 500 | file > 16,777,215 bytes, unreadable, internal error | `server error\n` | `text/plain` |

Extension map (case-insensitive): `.html .htm`→`text/html`,
`.txt`→`text/plain`, `.css`→`text/css`, `.js`→`text/javascript`,
`.png`→`image/png`, `.jpg .jpeg`→`image/jpeg`, else
`application/octet-stream`. An empty file is a 200 with a zero-length
DATA frame.

## §6 Connection lifecycle

- **Server**: `./bserve ROOT PORT`, binds IPv4 0.0.0.0:PORT, handles
  connections one at a time (no concurrency in v1). Within a connection:
  loop frames forever. After each response the connection MUST stay open —
  multiple sequential requests per connection MUST work. Close only on
  EOF, socket error, or receiving ERR.
- **Client**: `./bcurl [-v] HOST:PORT/PATH [MORE_URLS...]` — one TCP
  connection per invocation, never a second one. One request per URL on
  that connection, stream ids 1..N, then close. Missing PATH → `/`.

## §7 Client observable behavior

- Body bytes go to **stdout**, raw and binary-safe. Everything else
  (errors, -v output) goes to **stderr** — stdout must stay pipeable.
- `-v`: for every frame in both directions (`»` sent, `«` received), print
  to stderr: direction, type name, stream id, LENGTH, then a standard
  16-bytes-per-line hexdump with ASCII gutter.
- Exit codes: **0** = :status 2xx · **1** = 4xx · **2** = 5xx ·
  **3** = connect failure, protocol violation, EOF before a complete
  response, or ERR received. Body is printed to stdout regardless of
  status class.

## §8 Security & limits

- Structural caps: LENGTH ≤ 16,777,215; each String ≤ 255 bytes. Both are
  enforced by the wire format itself.
- Path containment (realpath under root) is REQUIRED, not optional.
- No timeouts in v1. No logging requirements in v1.

---

## Appendix: §9 Reference vectors (implementations MUST match byte-for-byte)

**A — canonical request** for `bcurl localhost:9000/index.html` (minimal):

    00 00 22  02  00  00 00 01          HEADERS, len 34, stream 1
    81 03 47 45 54                      :method = "GET"
    82 0B 2F 69 6E 64 65 78 2E 68 74 6D 6C    :path = "/index.html"
    84 0E 6C 6F 63 61 6C 68 6F 73 74 3A 39 30 30 30   host = "localhost:9000"

**A2 — same request plus a literal entry** (demonstrates the 0x00 form;
payload 54 = 0x36 bytes, header `00 00 36 02 00 00 00 01`):

    ...A as above, then:
    00 0A 75 73 65 72 2D 61 67 65 6E 74 07 62 63 75 72 6C 2F 31
    "user-agent" = "bcurl/1"

**B — 200 response** where `www/index.html` contains exactly
`<h1>ok</h1>\n` (12 bytes), stream 1:

    00 00 10  02  00  00 00 01   HEADERS, len 16
    83 03 32 30 30               :status = "200"
    87 09 74 65 78 74 2F 68 74 6D 6C   content-type = "text/html"
    00 00 0C  01  00  00 00 01   DATA, len 12
    3C 68 31 3E 6F 6B 3C 2F 68 31 3E 0A   "<h1>ok</h1>\n"

**C — 404** (stream 1):

    00 00 11 02 00 00 00 01 | 83 03 34 30 34 87 0A 74 65 78 74 2F 70 6C 61 69 6E
    00 00 0A 01 00 00 00 01 | 6E 6F 74 20 66 6F 75 6E 64 0A        "not found\n"

**D — 400** (stream 1):

    00 00 11 02 00 00 00 01 | 83 03 34 30 30 87 0A 74 65 78 74 2F 70 6C 61 69 6E
    00 00 0C 01 00 00 00 01 | 62 61 64 20 72 65 71 75 65 73 74 0A  "bad request\n"

**E — 500** (stream 1):

    00 00 11 02 00 00 00 01 | 83 03 35 30 30 87 0A 74 65 78 74 2F 70 6C 61 69 6E
    00 00 0D 01 00 00 00 01 | 73 65 72 76 65 72 20 65 72 72 6F 72 0A  "server error\n"

**F — unknown type MUST be skipped.** `00 00 03 42 00 00 00 01 | DE AD BE`
may be injected between any two frames; the receiver proceeds exactly as
if it were absent.

**G — malformed request → D.** A HEADERS frame whose entire payload is
`80` (indexed entry, index 0 — invalid):

    00 00 01 02 00 00 00 01 | 80      → server replies with Vector D.

**Hand-check requirement:** before coding, confirm you can decode Vector A
and Vector B on paper. If you cannot annotate these bytes, the spec is not
finished.
