# BCURLP/1 — Binary Curl Protocol (Version 1)

BCURLP/1 is a high-performance, single-connection binary application protocol layered directly over TCP. It brings core HTTP/2 mechanisms—discrete binary framing, HPACK-lite static table compression, single-connection preservation, and forward-compatible frame skipping—into an airtight, hand-crafted engineering implementation.

---

## 1. Repository Directory & Artifact Map

| Path | Category | LOC / Size | Description |
|---|---|---|---|
| [`specs.md`](specs.md) | **Core Deliverable** | ~140 lines | Formal 2-page protocol specification with §9 reference vectors appendix |
| [`bserve.py`](bserve.py) | **Core Deliverable** | 95 LOC | Conforming single-connection server (`<= 100` LOC, 0 comments, fully typed) |
| [`bcurl.py`](bcurl.py) | **Core Deliverable** | 100 LOC | Conforming binary client (`<= 100` LOC, 0 comments, fully typed) |
| [`hexdump_annotated.txt`](hexdump_annotated.txt) | **Core Deliverable** | 120 lines | 100% byte-accounted wire trace of live exchange with 60-second walkthrough |
| [`docs/architecture.md`](docs/architecture.md) | **Documentation** | ~170 lines | End-to-end architecture, protocol layers, and Mermaid interaction diagrams |
| [`docs/design.md`](docs/design.md) | **Documentation** | ~190 lines | Component flowcharts, client state machine, HPACK codec, and rig design |
| [`t1_rig.py`](t1_rig.py) | **Testing Oracle** | 335 lines | Automated black-box conformance harness for Track 1 (19 test cases) |
| [`t2_rig.py`](t2_rig.py) | **Testing Oracle** | 280 lines | Automated black-box conformance fake-server for Track 2 (16 test cases) |
| [`verify.py`](verify.py) | **Audit Suite** | 125 lines | Independent audit script verifying 20 strict invariants (LOC, purity, vectors) |
| [`tests/verify.py`](tests/verify.py) | **Audit Suite** | 125 lines | Location-independent verification script inside the tests folder |
| [`tests/reports/`](tests/reports/) | **Audit Reports** | 4 files | Execution logs for Tier 0 demo, Tier 1 rigs, Tier 2 audit, and Tier 3 defense |
| [`www/`](www/) | **Server Root** | 4 fixtures | Document root fixtures: `index.html` (12 B), `empty.txt` (0 B), `big.bin` (1 MiB), `subdir/` |
| [`bserve`](bserve) / [`bserve.bat`](bserve.bat) | **Executable CLI** | — | POSIX and Windows shell wrappers for the server |
| [`bcurl`](bcurl) / [`bcurl.bat`](bcurl.bat) | **Executable CLI** | — | POSIX and Windows shell wrappers for the client |
| [`.gitignore`](.gitignore) | **Repository Config** | — | Strictly ignores internal operator scaffolding and Python cache |

---

## 2. Protocol Framing & Core Invariants

### 8-Byte Word-Aligned Header
Every transmission begins with a fixed 8-byte header:

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       LENGTH (24 bits)        |  TYPE (8 bits)|
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| FLAGS (8 bits)|                   STREAM_ID (24 bits)         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     PAYLOAD (LENGTH Bytes)                    |
|                              ...                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

- **LENGTH (24 bits)**: Caps frame payloads at $16\,\text{MiB}$ ($16{,}777{,}215$ bytes), matching HTTP/2's default maximum frame payload.
- **TYPE (8 bits)**: `0x01` (DATA), `0x02` (HEADERS), `0x03` (ERR).
- **FLAGS (8 bits)**: Extension hooks (`0x00` in v1).
- **STREAM_ID (24 bits)**: Sequential request/response stream identifier (`1, 2, 3...`).

### The Skip Rule
An implementation encountering an unrecognized frame type MUST read the 8-byte header, read and discard exactly `LENGTH` payload bytes, and resume processing. It MUST NOT crash, close, or desynchronize byte alignment. This guarantees version 2 forward compatibility.

### HPACK-Lite Static Table
Headers are encoded either as indexed names from the static table (`0x80 | index`) followed by a length-prefixed value string, or as literal pairs (`0x00`) with length-prefixed name and value strings.

| Index | Name | Role | Index | Name | Role |
|:---:|:---|:---|:---:|:---|:---|
| **1** | `:method` | Request (`GET`) | **6** | `accept` | Optional |
| **2** | `:path` | Request (starts with `/`) | **7** | `content-type` | Response (`text/html`, etc.) |
| **3** | `:status` | Response (`200`, `400`, `404`, `500`) | **8** | `content-length`| Unused in v1 |
| **4** | `host` | Request (`localhost:9000`) | **9** | `server` | Optional |
| **5** | `user-agent` | Optional | **10** | `date` | Optional |

---

## 3. Quick Start & Execution

### Starting the Server
```bash
python bserve.py ./www 9000
```
Enable frame diagnostic summaries to `stderr`:
```bash
BSERVE_DEBUG=1 python bserve.py ./www 9000
```

### Running the Client
Fetch a resource and write binary body bytes directly to `stdout`:
```bash
python bcurl.py localhost:9000/index.html
```

Inspect frames with verbose 16-byte hex dumps and ASCII gutter to `stderr`:
```bash
python bcurl.py -v localhost:9000/index.html
```

Fetch multiple resources sequentially over **one single TCP connection**:
```bash
python bcurl.py localhost:9000/index.html localhost:9000/empty.txt localhost:9000/big.bin
```

---

## 4. Verification & Testing Suite

All tests can be executed across four distinct audit tiers.

### Tier 0: Live Demo
Run the server in one shell and execute behavior checks in another:
```bash
python bcurl.py -v localhost:9000/index.html                                          # 200 OK + Hexdump
python bcurl.py localhost:9000/nope.html                                             # 404 Not Found (Exit 1)
python bcurl.py localhost:9000/../etc/passwd                                         # 400 Bad Request (Exit 1)
python bcurl.py -v localhost:9000/index.html localhost:9000/empty.txt localhost:9000/index.html  # Keep-Alive sid=1,2,3
```
*Report*: [`tests/reports/tier0_demo_report.txt`](tests/reports/tier0_demo_report.txt)

### Tier 1: Conformance Rigs (35 / 35 PASS)
- **Track 1 Server Rig** (19 black-box socket tests):
  ```bash
  python t1_rig.py 9000
  ```
- **Track 2 Client Rig** (16 fake-server subprocess tests):
  ```bash
  python t2_rig.py 9001
  ```
*Report*: [`tests/reports/tier1_rigs_report.txt`](tests/reports/tier1_rigs_report.txt)

### Tier 2: Independent Audit (20 / 20 PASS)
Execute the single-command comprehensive audit:
```bash
python verify.py
```
*Report*: [`tests/reports/tier2_audit_report.txt`](tests/reports/tier2_audit_report.txt)

### Tier 3: Oral Defense
Master the one-sentence defenses for the eight graded architectural decisions:
*Guide*: [`tests/reports/defense_guide.md`](tests/reports/defense_guide.md)

---

## 5. Engineering Invariants & Scorecard

- **LOC Constraints**: `bserve.py` is **95 LOC**; `bcurl.py` is **100 LOC** (strictly `<= 100` ceiling).
- **Zero Comments / Docstrings**: Code is self-documenting; names and type hints carry 100% of intent.
- **Pure Loops**: Exclusively plain `for`/`if`/`while` constructs (no comprehensions, lambdas, or generator expressions).
- **Output-Surface Purity**:
  - `stdout`: Pure protocol surface. Server writes 0 bytes to `stdout`. Client writes raw body bytes only.
  - `stderr`: Dedicated diagnostic surface (`-v` hexdumps and single-line error notes).
- **Security & Containment**: Path traversal is immunized via `os.path.commonpath([root, path]) == root` and leading slash stripping.
