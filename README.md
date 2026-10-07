# BCURLP/1 — Binary Curl Protocol (Version 1)

BCURLP/1 is a lightweight binary application protocol layered directly over TCP. It adopts key architectural mechanisms from HTTP/2 in a minimal, highly defensible design.

## Architecture & Frame Layout

Every transmission occurs in discrete binary frames over a single persistent TCP connection.

### Fixed 8-Byte Frame Header
- **LENGTH (24 bits)**: Big-endian payload size (0 to 16,777,215 bytes). Caps corrupt frames at 16 MB.
- **TYPE (8 bits)**: `0x01` (DATA), `0x02` (HEADERS), `0x03` (ERR).
- **FLAGS (8 bits)**: Extension hooks (`0x00` in v1).
- **STREAM_ID (24 bits)**: Stream identifier (1, 2, 3...).

### The Skip Rule
Any receiver encountering an unrecognized frame type reads the 8-byte header, reads and discards exactly `LENGTH` payload bytes, and resumes processing without connection termination or byte desynchronization.

### Header Block Encoding
Headers utilize HPACK's foundational mechanisms:
1. **Indexed Entries (`0x80 | index`)**: 1-byte control code selecting from the 10-entry Static Table (e.g., Index 1: `:method`, Index 2: `:path`, Index 3: `:status`, Index 4: `host`, Index 7: `content-type`), followed by a length-prefixed value.
2. **Literal Entries (`0x00`)**: Length-prefixed literal name followed by length-prefixed literal value.

---

## Deliverables

1. **`specs.md`**: Complete, self-contained two-page protocol specification with test vectors.
2. **`bserve.py`**: Conforming single-connection server (`<= 100` LOC, zero comments, type-annotated).
3. **`bcurl.py`**: Conforming binary client (`<= 100` LOC, zero comments, type-annotated).
4. **`hexdump_annotated.txt`**: Exhaustive byte-by-byte annotated wire exchange trace with 60-second executive walkthrough.
5. **`t1_rig.py` & `t2_rig.py`**: Independent automated black-box test oracles.

---

## Usage

### Running the Server
```bash
python bserve.py ./www 9000
```
Or using the executable wrapper:
```bash
./bserve ./www 9000
```

### Running the Client
```bash
python bcurl.py localhost:9000/index.html
```
With verbose frame hexdump to `stderr`:
```bash
python bcurl.py -v localhost:9000/index.html
```
Multiple URLs on a single persistent TCP connection:
```bash
python bcurl.py localhost:9000/index.html localhost:9000/empty.txt
```

---

## Running Automated Conformance Tests

### Track 1 Server Tests (19 Cases)
```bash
python bserve.py ./www 9000 &
python t1_rig.py 9000
```

### Track 2 Client Tests (16 Cases)
```bash
python t2_rig.py 9001
```

All 35 conformance test cases pass cleanly with 100% green status.
