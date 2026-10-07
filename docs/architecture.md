# BCURLP/1 System Architecture

This document specifies the structural architecture, protocol layer separation, wire framing mechanics, and component interactions of **BCURLP/1 (Binary Curl Protocol, Version 1)**.

---

## 1. System Overview

BCURLP/1 is a streamlined binary application protocol designed to deliver HTTP semantics over a single persistent TCP connection. It eliminates text-parsing overhead and line-oriented ambiguities by using fixed-width binary frame headers and HPACK-inspired header block encodings.

```mermaid
flowchart TD
    subgraph ClientLayer["Track 2: Client (bcurl)"]
        CLI["CLI Argument Parser"] --> URLP["URL & Target Parser"]
        URLP --> REQB["Request Frame Builder"]
        REQB --> CSOCK["Single TCP Socket"]
        CSOCK --> RESPDEC["Response Frame Decoder"]
        RESPDEC --> STDOUT["stdout: Raw Body (Binary-Safe)"]
        RESPDEC --> STDERR["stderr: -v Hexdump & Diagnostics"]
    end

    subgraph WireLayer["Network Transport"]
        CSOCK <== "Single TCP Connection (Raw Frames)" ==> SSOCK["TCP Server Socket (0.0.0.0:PORT)"]
    end

    subgraph ServerLayer["Track 1: Server (bserve)"]
        SSOCK --> FRAMER["8-Byte Header & Frame Reader"]
        FRAMER --> DISP{"Frame Dispatcher"}
        DISP -- "TYPE 0x02 (HEADERS)" --> HDEC["Header Block Decoder"]
        DISP -- "Unknown TYPE (e.g. 0x42)" --> SKIP["The Skip Rule (Discard LENGTH bytes)"]
        DISP -- "TYPE 0x03 (ERR)" --> SCLOSE["Immediate Connection Close"]
        HDEC --> SEC["Path Containment & Security Validator"]
        SEC --> FS["Document Root File Resolver (www/)"]
        FS --> RESPB["Response Frame Builder"]
        RESPB --> SSOCK
    end
```

---

## 2. Layered Protocol Architecture

The protocol is partitioned into four distinct, non-overlapping architectural layers:

```mermaid
graph TD
    L4["Layer 4: HTTP Semantics (GET, Status 200/400/404/500, MIME Mapping)"]
    L3["Layer 3: Header Block Encoding (HPACK-Lite: 10 Static Indices + Literal Strings)"]
    L2["Layer 2: Framing & Multiplexing Headroom (8-Byte Header, Skip Rule)"]
    L1["Layer 1: Reliable Stream Transport (Persistent TCP Stream, read_exact)"]

    L4 --> L3
    L3 --> L2
    L2 --> L1
```

### Layer 1: Reliable Stream Transport
- **Mechanism**: Bare IPv4 TCP socket without TLS or handshakes.
- **Invariant**: The first byte on the socket is byte 0 of the first frame header.
- **Short-Read Protection**: All network reads must pass through a `read_exact(sock, n)` loop to handle TCP packet fragmentation.
- **Connection Lifecycle**: Single TCP connection. The client never opens a second socket; the server maintains the connection across sequential requests.

### Layer 2: Framing & The Skip Rule
- **Mechanism**: Uniform 8-byte fixed header preceding every payload.
- **Forward Compatibility Guarantee**: An implementation encountering an unrecognized frame `TYPE` MUST read the 8-byte header, read and discard exactly `LENGTH` payload bytes, and continue processing without connection termination or byte desynchronization.

### Layer 3: Header Block Encoding
- **Mechanism**: Compact two-mode serialization derived from HPACK (RFC 7541).
- **Indexed Form (`0x80 | index`)**: 1-byte control code selecting from the 10-entry static table, followed by a length-prefixed string value.
- **Literal Form (`0x00`)**: 1 control byte, length-prefixed string name, and length-prefixed string value.

### Layer 4: HTTP Semantics
- **Requests**: Only `GET` method supported. `:path` must begin with `/`. `host` header is mandatory.
- **Responses**: Exactly one `HEADERS` frame followed by exactly one `DATA` frame per request stream.

---

## 3. Frame Header Layout & Width Defense

Every frame transmitted over the wire begins with the fixed 8-byte header:

```
+---------------------------------------------------------------+
|                       BCURLP/1 Frame Header                   |
|                          (8 Bytes Total)                      |
+-------------------------------+---------------+---------------+
|       LENGTH (24 bits)        | TYPE (8 bits) | FLAGS (8 bits)|
|   Payload size (0..16,777,215)| 1=DATA 2=HDR  |     0x00      |
+-------------------------------+---------------+---------------+
|                     STREAM_ID (24 bits)                       |
|               Request/Response identifier (1..N)              |
+---------------------------------------------------------------+
|                      PAYLOAD (LENGTH Bytes)                   |
|                   DATA bytes / Header Entries                 |
+---------------------------------------------------------------+
```

```mermaid
flowchart LR
    F0["Byte 0..2: LENGTH (24 bits)\nCaps payload at 16 MiB"] --> F3["Byte 3: TYPE (8 bits)\n0x01 DATA, 0x02 HEADERS, 0x03 ERR"]
    F3 --> F4["Byte 4: FLAGS (8 bits)\n0x00 in v1 (Extension hook)"]
    F4 --> F5["Byte 5..7: STREAM_ID (24 bits)\nStream sequence 1, 2, 3..."]
```

### Architectural Defense of Chosen Widths
1. **LENGTH (24 bits, 3 bytes)**:
   - Caps corrupt or malicious payload allocations at exactly $16\,\text{MiB}$ ($16{,}777{,}215$ bytes).
   - Matches the default maximum frame payload of HTTP/2 (RFC 7540 §4.1).
   - Allows full-sized media and documentation files while enforcing bounded server memory.
2. **TYPE (8 bits, 1 byte)**:
   - Provides 256 distinct frame type opcodes. While v1 utilizes only 3 (`DATA`, `HEADERS`, `ERR`), the 8-bit width combined with the **Skip Rule** provides forward compatibility for version 2 extensions (`SETTINGS`, `PING`, `RST_STREAM`).
3. **FLAGS (8 bits, 1 byte)**:
   - Serves as the cheapest possible backward-compatible feature flag (e.g., `END_STREAM`, `END_HEADERS` in future iterations). Senders emit `0x00`; receivers accept any value.
4. **STREAM_ID (24 bits, 3 bytes)**:
   - Supports up to $16{,}777{,}215$ sequential streams per connection.
   - Combines with $24 + 8 + 8 = 40$ bits to form an exactly 64-bit ($8\text{-byte}$) word-aligned header. Aligned headers are trivial to parse with standard bitwise shifts and easy to inspect in hex dumps.

---

## 4. End-to-End Exchange Sequence

The following sequence diagram illustrates a complete, persistent multi-request session:

```mermaid
sequenceDiagram
    autonumber
    actor User as Client User / Shell
    participant Client as bcurl (Client)
    participant Socket as TCP Stream (Port 9000)
    participant Server as bserve (Server)
    participant FS as Local Filesystem (www/)

    User->>Client: Execute bcurl -v localhost:9000/index.html localhost:9000/empty.txt
    Client->>Socket: TCP Connect (127.0.0.1:9000)
    Socket->>Server: Accept Connection

    Note over Client,Server: Stream 1: Request for /index.html
    Client->>Socket: HEADERS Frame (sid=1, len=34, :method=GET, :path=/index.html, host)
    Socket->>Server: Read exact 8-byte header + 34-byte payload
    Server->>FS: Resolve and verify realpath(www/index.html)
    FS-->>Server: File found (12 bytes: "<h1>ok</h1>\n")
    Server->>Socket: HEADERS Frame (sid=1, len=16, :status=200, content-type=text/html)
    Server->>Socket: DATA Frame (sid=1, len=12, "<h1>ok</h1>\n")
    Socket-->>Client: Receive HEADERS (sid=1, status=200)
    Socket-->>Client: Receive DATA (sid=1, 12 bytes)
    Client->>User: stdout: "<h1>ok</h1>\n"

    Note over Client,Server: Stream 2: Sequential Request on SAME Connection
    Client->>Socket: HEADERS Frame (sid=2, len=33, :method=GET, :path=/empty.txt, host)
    Socket->>Server: Read exact 8-byte header + 33-byte payload
    Server->>FS: Resolve and verify realpath(www/empty.txt)
    FS-->>Server: File found (0 bytes)
    Server->>Socket: HEADERS Frame (sid=2, len=17, :status=200, content-type=text/plain)
    Server->>Socket: DATA Frame (sid=2, len=0, empty payload)
    Socket-->>Client: Receive HEADERS (sid=2, status=200)
    Socket-->>Client: Receive DATA (sid=2, 0 bytes)
    Client->>User: stdout: (0 bytes)

    Client->>Socket: Close TCP Connection
    Server->>Server: Detect EOF, close client socket, wait for next connection
```

---

## 5. Security & Isolation Architecture

```mermaid
flowchart TD
    INPATH["Client :path string (e.g. /../etc/passwd)"] --> LSTRIP["Strip Leading Slashes (lstrip)"]
    LSTRIP --> JOIN["os.path.join(root_dir, stripped_path)"]
    JOIN --> REAL["os.path.realpath (Canonicalize symlinks & ..)"]
    REAL --> ROOT["root_dir = os.path.realpath(ROOT)"]
    ROOT --> CP{"os.path.commonpath([root_dir, cand_path]) == root_dir"}
    CP -- "No (Path Escaped Root)" --> E400["Emit 400 Bad Request"]
    CP -- "Yes (Safe)" --> EXIST{"File Exists and is Regular File?"}
    EXIST -- "No (Missing or Directory)" --> E404["Emit 404 Not Found"]
    EXIST -- "Yes" --> READ["Read File Bytes & Check Size <= 16 MiB"]
```

1. **Path Traversal Immunization**:
   - Stripping leading `/` before joining avoids `os.path.join` discarding the document root.
   - Canonicalizing via `os.path.realpath` resolves `..` elements.
   - Enforcing `os.path.commonpath([root_dir, cand]) == root_dir` prevents the classic prefix vulnerability where `/srv/www-secret` would improperly match `/srv/www` under a naive `startswith` check.
2. **Buffer Exhaustion Defense**:
   - Frame `LENGTH` is capped at $16{,}777{,}215$ bytes by the 24-bit wire width.
   - String values within header blocks are capped at 255 bytes by the 1-byte length prefix.

---
BISHWAYAN CHATTERJEE -- 24BCS10200
