# BCURLP/1 Component Design & Implementation

This document describes the concrete software design, state machines, algorithmic flowcharts, and error-handling precedence implemented in **BCURLP/1**.

---

## 1. Server Engine Design (`bserve.py`)

The server is structured as an iterative, single-threaded connection handler that keeps the TCP socket open until the client disconnects or an error frame arrives.

```mermaid
flowchart TD
    START(["Server Start: bserve ROOT PORT"]) --> INIT["Resolve root_dir = realpath(ROOT)\nBind 0.0.0.0:PORT with SO_REUSEADDR\nListen for connections"]
    INIT --> ACCEPT["Accept incoming TCP connection"]
    ACCEPT --> READHDR["read_exact(sock, 8)\nRead 8-byte frame header"]
    READHDR --> CHECKHDR{"Received exact 8 bytes?"}
    CHECKHDR -- "No (Client Closed / EOF)" --> CLOSE["Close client connection"]
    CLOSE --> ACCEPT

    CHECKHDR -- "Yes" --> READPAY["Extract length, ftype, sid\nread_exact(sock, length)"]
    READPAY --> CHECKPAY{"Received exact length bytes?"}
    CHECKPAY -- "No (Truncated Frame / Early EOF)" --> CLOSE

    CHECKPAY -- "Yes" --> FTYPE{"Evaluate Frame TYPE"}
    FTYPE -- "0x03 (ERR Frame)" --> CLOSE
    FTYPE -- "Unknown (e.g. 0x42) or 0x01 (DATA)" --> SKIP["Apply Skip Rule:\nDiscard payload bytes, do not reply"]
    SKIP --> READHDR

    FTYPE -- "0x02 (HEADERS Frame)" --> DECODE["decode_headers(payload)"]
    DECODE --> EVAL["resolve_request(root_dir, hdrs)"]
    EVAL --> ENCODE["encode_response(sid, status, ctype, body)"]
    ENCODE --> SEND["sock.sendall(response_bytes)"]
    SEND --> READHDR
```

### Precedence of Server Error Decisions
The server enforces a deterministic order of evaluation for every incoming request:

```mermaid
flowchart TD
    D0["Incoming HEADERS Frame Payload"] --> D1{"Header block decoded cleanly?"}
    D1 -- "Malformed control byte, bad index, truncated string" --> R400["400 Bad Request\n'bad request\\n'"]
    D1 -- "Valid syntax" --> D2{":method == 'GET' and :path starts with '/' and 'host' present?"}
    D2 -- "No (Missing or invalid mandatory header)" --> R400
    D2 -- "Yes" --> D3{"Rewrite path: '/' -> '/index.html'\nStrip leading slash and check containment"}
    D3 -- "realpath escapes document root" --> R400
    D3 -- "Safe containment" --> D4{"File exists and is not a directory?"}
    D4 -- "Directory or non-existent file" --> R404["404 Not Found\n'not found\\n'"]
    D4 -- "File exists" --> D5{"File readable and size <= 16,777,215 bytes?"}
    D5 -- "File > 16 MiB or OSError" --> R500["500 Server Error\n'server error\\n'"]
    D5 -- "Success" --> R200["200 OK\nEmit file contents with mapped MIME type"]
```

---

## 2. Client Engine Design (`bcurl.py`)

The client maintains an explicit response state machine for each URL requested on the connection.

### Response State Machine

```mermaid
stateDiagram-v2
    [*] --> Idle: Initialize CLI args & single TCP socket
    Idle --> Connected: Connect to HOST:PORT
    Connected --> SendingRequest: Stream ID = N (1..Total)
    SendingRequest --> WaitingHeaders: sendall(HEADERS Frame)

    WaitingHeaders --> WaitingHeaders: Unknown Frame received (Skip & Hexdump if -v)
    WaitingHeaders --> ErrorExit: Received ERR Frame (Exit code 3)
    WaitingHeaders --> ErrorExit: Received DATA Frame (Shape violation: Exit code 3)
    WaitingHeaders --> ErrorExit: Socket EOF before HEADERS (Exit code 3)
    WaitingHeaders --> WaitingData: Received HEADERS Frame (Parse :status)

    WaitingData --> WaitingData: Unknown Frame received (Skip & Hexdump if -v)
    WaitingData --> ErrorExit: Received second HEADERS (Shape violation: Exit code 3)
    WaitingData --> ErrorExit: Received ERR Frame (Exit code 3)
    WaitingData --> ErrorExit: Socket EOF before DATA (Exit code 3)
    WaitingData --> StreamComplete: Received DATA Frame (stdout.buffer.write)

    StreamComplete --> SendingRequest: More URLs remaining (Stream ID += 1)
    StreamComplete --> Finished: All URLs completed
    Finished --> [*]: Map status to exit code (2xx->0, 4xx->1, 5xx->2)
    ErrorExit --> [*]: Exit code 3
```

### Multi-URL Single-Connection Loop
When invoked with multiple URLs (e.g. `bcurl localhost:9000/a localhost:9000/b`), the client:
1. Connects to `HOST:PORT` once at startup.
2. Iterates over URLs using sequential stream identifiers (`sid = 1, 2, 3...`).
3. Sends request $N$ and blocks until response $N$ (`HEADERS` then `DATA`) is fully received.
4. Writes body bytes sequentially to standard output.
5. Closes the socket only after the final URL completes.

---

## 3. Header Block Codec (HPACK-Lite)

The header block serialization uses HPACK's first two mechanisms: static table indexing and length-prefixed strings.

```mermaid
flowchart TD
    INBYTE["Read Next Control Byte (ctrl)"] --> C0{"ctrl == 0x00?"}
    C0 -- "Yes" --> LIT["Literal Entry:\nRead string name length (1 byte)\nRead name UTF-8 bytes\nRead string value length (1 byte)\nRead value UTF-8 bytes"]
    C0 -- "No" --> C80{"(ctrl & 0x80) != 0?"}
    C80 -- "No" --> MAL1["Malformed Entry (0x01..0x7F) -> 400 Bad Request"]
    C80 -- "Yes" --> IDX["Extract index = ctrl & 0x7F"]
    IDX --> CHKIDX{"1 <= index <= 10?"}
    CHKIDX -- "No (Index 0 or Reserved 11..127)" --> MAL2["Malformed Index -> 400 Bad Request"]
    CHKIDX -- "Yes" --> LOOKUP["Look up name in Static Table:\n1=:method, 2=:path, 3=:status, 4:host,\n5:user-agent, 6:accept, 7:content-type,\n8:content-length, 9:server, 10:date"]
    LOOKUP --> READVAL["Read string value length (1 byte)\nRead value UTF-8 bytes"]
```

### Static Table Definition
| Index | Wire Byte | Header Name | Primary Role |
|---|---|---|---|
| 1 | `0x81` | `:method` | Mandatory in requests (`GET`) |
| 2 | `0x82` | `:path` | Mandatory in requests (starts with `/`) |
| 3 | `0x83` | `:status` | Mandatory in responses (`200`, `400`, `404`, `500`) |
| 4 | `0x84` | `host` | Mandatory in requests |
| 5 | `0x85` | `user-agent` | Optional metadata |
| 6 | `0x86` | `accept` | Optional content negotiation |
| 7 | `0x87` | `content-type` | Mandatory in responses (`text/html`, etc.) |
| 8 | `0x88` | `content-length` | Unused in v1 (frame LENGTH carries size) |
| 9 | `0x89` | `server` | Optional response header |
| 10 | `0x8A` | `date` | Optional response header |

---

## 4. Diagnostic Hexdump Formatter (`-v`)

The `-v` flag formats all sent and received frames directly to `stderr` with a two-column 16-byte hex dump and ASCII gutter:

```mermaid
flowchart LR
    FRAME["Frame (8-byte header + payload)"] --> HDRLINE["Emit direction, type, sid, length\n(e.g. '» HEADERS sid=1 len=34')"]
    HDRLINE --> CHUNKS["Split frame into 16-byte rows"]
    CHUNKS --> ROW["Format row:\nOffset (8 hex digits)\nGroup 1 (8 hex bytes)\nGroup 2 (8 hex bytes)\nASCII gutter (| printable ASCII or . |)"]
    ROW --> STDERR["Write to sys.stderr"]
```

Example formatted output:
```text
» HEADERS  sid=1 len=34
00000000  00 00 22 02 00 00 00 01  81 03 47 45 54 82 0b 2f  |..".......GET../|
00000010  69 6e 64 65 78 2e 68 74  6d 6c 84 0e 6c 6f 63 61  |index.html..loca|
00000020  6c 68 6f 73 74 3a 39 30  37 37                    |lhost:9077|
```

---

## 5. Conformance Rig Architectures

Two independent test rigs enforce protocol compliance using black-box oracles:

```mermaid
flowchart TD
    subgraph T1["Track 1 Rig: t1_rig.py (Fake Client)"]
        TC["19 Test Cases"] --> TSOCK["Open raw TCP socket to bserve"]
        TSOCK --> TSEND["Send canned test vectors"]
        TSEND --> TRECV["read_exact response frames"]
        TRECV --> TDIFF["Assert exact expected bytes and assert empty socket drain"]
    end

    subgraph T2["Track 2 Rig: t2_rig.py (Fake Server)"]
        T2S["Fake Server Socket on 127.0.0.1:PORT"] --> T2ACC["Accept connection\n(Tripwire: Fail if second accept occurs)"]
        T2ACC --> T2REQ["Decode bcurl request frame & assert semantics"]
        T2REQ --> T2RESP["Send canned response vector stamped with request sid"]
        T2RESP --> T2PROC["Subprocess: run bcurl.py"]
        T2PROC --> T2CHK["Assert stdout bytes, stderr contents, and exit code"]
    end
```

### The Second-Accept Tripwire
In `t2_rig.py`, Rule R1 (never open a second connection) is mechanically verified: after serving the requests for multi-URL tests, the rig sets a non-blocking timeout on `socket.accept()`. If `bcurl` attempts to open an auxiliary socket, the tripwire triggers and fails the test immediately.

---
BISHWAYAN CHATTERJEE -- 24BCS10200
