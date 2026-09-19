# Python zstd for tailing concatenated independent frames (partial-frame tail semantics)

**Date:** 2026-09-19
**Question:** Which Python zstd library should tail a file that is a concatenation of
independent Zstandard frames, and how do you implement partial-frame tail semantics
(complete-frame-only offset, corrupt-frame skip, shrinking file) on Python 3.12?

**Scope:** the DSH session log `$DSH_HOME/sessions/<project>/<session-id>/session.jsonl.zstd`,
whose reference implementation is the JS `decodeFrames()` in
`ai-usage/dsh-mongodb-usage-hook.mjs` (lines 87-142).

**Verification method:** every behavioural claim below was executed against the real
libraries in a scratch venv (`zstandard` 0.25.0, `pyzstd` 0.19.1, `backports.zstd` 1.7.0,
CPython 3.12.7, macOS arm64), and cross-checked against shipped source and PyPI metadata.
Claims marked *uncertain* were not verifiable from primary sources.

---

## 1. Recommendation

**Use `backports.zstd`.** Fallback: `zstandard` (python-zstandard). **Do not use `pyzstd`.**

The reasoning inverts the usual "most popular wins" default, so the three findings that
drive it:

1. **`pyzstd` is no longer a real alternative.** As of 0.19.x its source is a shim:
   ```python
   if sys.version_info < (3, 14):
       from backports import zstd
   else:
       from compression import zstd
   ```
   (`pyzstd/__init__.py`, installed 0.19.1). It re-exports `backports.zstd`'s
   `get_frame_size`/`get_frame_info` unchanged (`pyzstd.get_frame_size is
   backports.zstd.get_frame_size` → `True`) and is now a `py3-none-any` wheel. Choosing
   it buys **zero capability** over `backports.zstd` while adding **two** packages
   (`backports-zstd`, `typing-extensions`). It fails the "flat, minimal deps" bar for no gain.

2. **`backports.zstd` is the only one of the three that exposes the
   `ZSTD_findFrameCompressedSize` / `ZSTD_getFrameHeader` equivalents** you asked about
   (`get_frame_size`, `get_frame_info`). `zstandard` has **no** binding for compressed
   frame size — only `frame_header_size` (header only) and `frame_content_size`
   (*uncompressed* size). See §2.

3. **`backports.zstd` is API-identical to the stdlib `compression.zstd` added in Python
   3.14**, so the eventual move off the 3.12 floor is an import swap
   (`from backports import zstd` → `from compression import zstd`) rather than a rewrite.
   It declares `requires_python = ">=3.10,<3.14"`, i.e. it is *designed* to be replaced by
   the stdlib on 3.14.

`zstandard` remains a completely valid choice — it is more mature, and the core algorithm
in §5 is byte-for-byte identical in both libraries. Pick it if the team weighs
battle-testedness above the frame-boundary API and stdlib parity. The only functional
difference is the corrupt-frame recovery path in §6 (magic scan vs exact frame size).

### Comparison table

| | `zstandard` (python-zstandard) | `pyzstd` | `backports.zstd` |
|---|---|---|---|
| Latest / released | 0.25.0, 2025-09-14 | 0.19.1, 2025-12-13 | **1.7.0, 2026-08-15** (most recent) |
| Releases / first | 42, ~2016 | 22, ~2019 | 13, 2025 |
| Maturity | Highest; de-facto standard | Legacy; now a shim | Newest; is the engine `pyzstd` wraps |
| Runtime deps | **none** | `backports-zstd`, `typing-extensions` | **none** |
| `requires_python` | `>=3.9` | `>=3.10` | `>=3.10,<3.14` |
| Wheel, macOS arm64 + cp312 | `zstandard-0.25.0-cp312-cp312-macosx_11_0_arm64.whl` | `pyzstd-0.19.1-py3-none-any.whl` | `backports_zstd-1.7.0-cp312-cp312-macosx_11_0_arm64.whl` |
| Bundled zstd | 1.5.7 | 1.5.7 (via backports) | 1.5.7 |
| Decode concatenated frames | yes | yes | yes |
| `get_frame_size` (`findFrameCompressedSize`) | **no** | yes (re-export) | **yes** |
| `get_frame_info` (`getFrameHeader`) | no (only `get_frame_parameters`) | yes (re-export) | **yes** |
| `decompressobj()` / `unused_data` / `eof` | yes | yes | yes |
| `read_across_frames` | `stream_reader` only; **unimplemented on `decompress()`** | n/a | n/a |

Maintenance note: `zstandard` went 0.24.0 (2025-08-17) → 0.25.0 (2025-09-14), so it is
alive; `backports.zstd` shipped 1.4.0→1.7.0 between 2026-05 and 2026-08, so it is
currently the more actively released of the two. *Uncertain:* neither has a published
support policy; "better maintained" here is release cadence and dependency hygiene, not a
governance guarantee.

---

## 2. Frame-boundary APIs — exact names

### `backports.zstd` (and stdlib `compression.zstd` on 3.14)

```python
get_frame_size(frame_buffer) -> int
# ZSTD_findFrameCompressedSize. Returns the size of the *first* frame,
# header + blocks + optional checksum. Verified: on a 2-frame concatenation it
# returns the FIRST frame's size only.
# Raises ZstdError("... Src size is incorrect.") if the buffer does not contain
# one complete frame; ZstdError("... Unknown frame descriptor.") if not a frame.

get_frame_info(frame_buffer) -> FrameInfo   # .decompressed_size, .dictionary_id
# ZSTD_getFrameHeader. Needs only the 6-18 byte header, so it succeeds on a
# TRUNCATED frame (verified) — useful, but it is NOT a completeness check.
```

### `zstandard`

```python
zstandard.frame_content_size(data) -> int
# UNCOMPRESSED size. -1 when the frame omits it (write_content_size=False); verified.
# Raises ZstdError("error when determining content size") on bad input.

zstandard.frame_header_size(data) -> int      # header only, e.g. 7
zstandard.get_frame_parameters(data) -> FrameParameters
# fields: content_size, dict_id, window_size, has_checksum   (verified)
# NOTE: no compressed-frame-size field. No ZSTD_findFrameCompressedSize binding.
```

**Consequence:** with `zstandard` you cannot ask "how long is this frame?" directly. You
must use `decompressobj()`'s consumed-byte count (§4), which decompresses the frame. That
is fine for the happy path; it matters only for corrupt-frame recovery (§6).

---

## 3. Decompressing exactly one frame; partial vs corrupt

**Both libraries draw a clean, reliable line — this is the single most important result.**

Create a fresh decompression object per frame and feed it the slice from the frame start:

```python
obj = ZstdDecompressor().decompressobj()   # zstandard
obj = ZstdDecompressor()                   # backports.zstd / pyzstd
out = obj.decompress(buf[pos:])            # buffer MAY contain following frames
```

| Input | `decompressobj().decompress()` | `ZstdDecompressor().decompress()` |
|---|---|---|
| complete frame | returns output, `eof is True` | returns output, `eof is True` |
| **truncated / partial frame** | **no exception, `eof is False`** | **no exception, `eof is False`** |
| **corrupt frame** | **raises `ZstdError`** | **raises `ZstdError`** |

Verified exhaustively: a frame truncated by 1, 2, 3, 4, 5, 6, 7, 8 and 10 bytes, and
truncated to 2 and 6 bytes (header-only), **never raised** — every one returned
`eof=False`. Corruption in the frame header or (when a checksum is present) in the
payload **always raised** `ZstdError`. There is **no overlap**: `eof=False` never
accompanies a corrupt frame, and a raising call is never a merely-partial frame.

So the discrimination the task calls "enormous" is available **directly and without
heuristics**:

- `eof is False` → **partial trailing frame** → stop, do not advance, retry next poll.
- `ZstdError` → **corrupt frame** → apply the skip rule (§6).

Two mechanical notes:

- **Output is produced even when `eof is False`.** A frame truncated by exactly 1 byte
  (the checksum byte) returned the full 32-byte payload with `eof=False`. So you must
  gate on `eof` and **discard** output when it is false. Never use partial output.
- `backports.zstd` additionally exposes `needs_input` (`True` when the decompressor wants
  more bytes) — `needs_input=True` corroborates `eof=False`, but `eof` alone is sufficient.

### Exception types

- `zstandard.ZstdError` — `zstandard.backend_c.ZstdError`, subclasses `Exception` only.
  No `.code`; the zstd error name is interpolated into the message.
- `backports.zstd.ZstdError` (and `pyzstd.ZstdError is backports.zstd.ZstdError` → `True`).
- The two classes are **unrelated** (`zstandard.ZstdError is backports.zstd.ZstdError` →
  `False`), so a migration changes which class you catch.

Representative messages observed (do **not** parse these — use `eof` instead):

| Situation | Message |
|---|---|
| truncated (one-shot `decompress()`) | `decompression error: did not decompress full frame` |
| corrupt header | `zstd decompressor error: Unknown frame descriptor` |
| corrupt header | `zstd decompressor error: Data corruption detected` |
| corrupt payload, checksum present | `zstd decompressor error: Restored data doesn't match checksum` |
| `get_frame_size` on incomplete | `... Zstd error message: Src size is incorrect.` |

---

## 4. Reading across frames and computing the new offset

**`read_across_frames` is a red herring for this problem.** In `zstandard` it exists only
on `stream_reader`/`stream_writer`; on `ZstdDecompressor.decompress()` the argument is
accepted but **raises**:

> `read_across_frames` controls whether to read multiple zstandard frames in the input.
> When False, decompression stops after reading the first frame. This feature is not yet
> implemented but the argument is provided for forward API compatibility…
> — `ZstdDecompressor.decompress` docstring, shipped `zstandard/backend_cffi.py`

It is also unusable for offset accounting: `ZstdDecompressionReader.tell()` returns the
position in the **uncompressed output**, not the compressed input. Measured: after
consuming frame 1 (17 compressed bytes, 8 uncompressed bytes), `tell()` returned `8`.
There is no API on the reader for "compressed bytes consumed".

**Use `unused_data` instead — it gives an exact frame length.**

```python
obj = decompressor.decompressobj()
out = obj.decompress(buf[pos:])
# obj.eof is True for a complete frame
consumed = len(buf) - pos - len(obj.unused_data)
pos += consumed
```

`unused_data` is the unconsumed remainder and is populated **only once `eof` is True**
(it is `b''` otherwise — do not read it in the partial case). Equivalently and more
simply, since `buf[pos:]` is the whole slice:

```python
pos = len(buf) - len(obj.unused_data)   # valid only when obj.eof
```

Verified exactly: for `blob = f1(17) + f2(17) + partial_f3(18)`, one
`decompressobj().decompress(blob)` returned f1's output, `eof=True`,
`unused_data` of length 35, and `len(blob) - len(unused_data) == 17 == len(f1)`.

This is **more precise than the JS reference**: JS infers the frame end by scanning for
the *next* magic, whereas `unused_data` reports the end the decompressor actually
stopped at. It therefore finds the last frame in the file correctly, which the magic scan
only approximates (see §6 on false magics).

Also note `decompressobj()` handles frames with **no content size in the header**
(`write_content_size=False`), whereas the one-shot `ZstdDecompressor.decompress()` raises
`could not determine content size in frame header` unless you pass `max_output_size`.
Another reason to use `decompressobj()`.

---

## 5. Recommended algorithm

The important structural change from the JS reference: **do not pre-scan for magic bytes
to find frame starts.** Walk frame-by-frame from a known-good start offset and let
`unused_data` tell you where each frame ends. Magic scanning is used **only** to recover
from a corrupt frame, because that is the only situation where you do not know the frame
length.

```python
import zstandard  # or: from backports import zstd as zstandard

MAGIC = b"\x28\xb5\x2f\xfd"  # 0xFD2FB528 little-endian


def decode_frames(buf: bytes, start: int, decompressor) -> tuple[list[str], int]:
    """Decode every COMPLETE frame at/after `start`.

    Returns (lines, offset) where `offset` is the byte position after the last
    successfully decoded frame -- never mid-frame. A trailing partial frame
    leaves `offset` unchanged so the next poll retries it.
    """
    pos = start
    lines: list[str] = []

    while pos < len(buf):
        if buf[pos : pos + 4] != MAGIC:
            break  # not a frame start: partial header, or non-zstd file

        obj = decompressor.decompressobj()
        try:
            out = obj.decompress(buf[pos:])
        except zstandard.ZstdError:
            # CORRUPT frame. Recover to the next frame start so the tail
            # cannot stall permanently. If there is none, stop without
            # advancing -- it may still be a partially-written frame.
            nxt = buf.find(MAGIC, pos + 4)
            if nxt == -1:
                break
            pos = nxt
            continue

        if not obj.eof:
            break  # PARTIAL trailing frame -- wait for more bytes

        pos = len(buf) - len(obj.unused_data)  # exact end of this frame
        lines.extend(line for line in out.decode("utf-8").split("\n") if line.strip())

    return lines, pos
```

Reuse one `ZstdDecompressor` for the lifetime of the tailer (verified safe across many
frames); only the per-frame `decompressobj()` is fresh.

### Caller-side rules

```python
size = os.path.getsize(path)
if size < offset:
    offset = 0                      # writer truncated to last complete frame
if size == offset:
    return                          # nothing new

with open(path, "rb") as f:
    f.seek(offset)                  # read only the new region, not the whole file
    buf = f.read()

lines, new_offset = decode_frames(buf, 0, decompressor)
offset = new_offset
```

Two deliberate differences from the JS reference:

- **Read from the offset, not the whole file.** JS does `readFile(file)` and slices; for
  an append-only log this re-reads everything each poll. `seek(offset)` is equivalent
  because `offset` is always a frame boundary, and is O(new bytes).
- **Plaintext fallback is a separate branch.** `session.jsonl` (uncompressed) contains no
  magic, so `decode_frames` correctly returns `([], 0)`. Detect it once, up front — the
  JS rule is "no magic anywhere in the buffer **and** `from == 0`" → decode the whole
  buffer as UTF-8 JSONL and set `offset = len(buf)`. Keep that rule; it is correct, and
  it must be applied by the caller, not inside the frame walker.

### Validated behaviour

All of the following were executed and passed:

| Scenario | Result |
|---|---|
| 3 complete frames from offset 0 | all 5 lines, offset == file length |
| incremental: f1+f2 then f3 appended | resumes at exact prior offset, no re-read, no loss |
| trailing partial frame | no lines, offset unchanged (stays at prior frame end) |
| partial frame completes next poll | decodes normally from the same offset |
| corrupt frame + later good frame | corrupt skipped, later frame decoded, offset lands at end |
| corrupt frame with **no** later frame | no advance past the last good frame |
| reused `ZstdDecompressor` across calls | correct |
| frames produced by Homebrew `zstd` CLI v1.5.7 | decoded correctly (interop confirmed) |

---

## 6. Corrupt-vs-partial discrimination and residual risks

**No heuristic is needed.** As established in §3 the library already distinguishes them:
partial → `eof is False`, corrupt → `ZstdError`. The "compare against frame content size
header / parse the error string" hedge in the task is unnecessary — do **not** string-match
`"Src size is incorrect"` or `"unexpected end of input"`; those messages are not API.

The real residual risks are different, and two of them are worth flagging:

### 6a. Payload corruption is invisible unless the frame carries a checksum  *(most important)*

Verified directly: flipping a byte mid-payload decodes to **silently wrong bytes** with
`eof=True` and no exception if the frame was written without a content checksum.

```
write_checksum=False -> decoded eof=True out=b'{"\x91":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}\n'
write_checksum=True  -> ZstdError: ... Restored data doesn't match checksum
```

Frame **header** corruption is always caught. Payload corruption is caught only with
`write_checksum=True`. The zstd C API does **not** write a checksum by default.

This limits the corrupt-frame rule in §5: it fires only on header corruption (or on
checksummed frames). Otherwise a corrupt frame decodes to garbage, the tailer advances
past it, and the damaged lines fail `json.loads` and are dropped — the same behaviour as
the JS reference, which has the identical exposure.

*Uncertain / action item:* I could not determine from primary sources whether DSH's writer
sets a content checksum. The team should check (compress a known payload with the DSH
writer and inspect `ZstdDecompressor().get_frame_parameters(frame).has_checksum`, or
compare frame length against a `write_checksum=False` frame). If it does not, and
corruption tolerance matters, the mitigation is at the writer, not the tailer. For the
tailer, the practical guard is that a garbage line almost always fails JSON parsing.

### 6b. The magic-byte scan is not sound on its own

The zstd magic `28 B5 2F FD` **can appear inside compressed payload bytes** (most easily
in a raw/uncompressed block, where literal bytes are stored verbatim; the JSONL text is a
plausible carrier). The JS `frameStarts()` pre-scan would then treat a false offset as a
frame start, fail to decode it, and — because a later real magic exists — "skip a corrupt
frame" that was never a frame, silently discarding data.

The §5 algorithm is largely immune: it never scans for magic on the happy path, and
`unused_data` gives true frame ends. Magic scanning happens **only** after a real
`ZstdError`, and only to find a resync point. With `backports.zstd` the skip can be made
exact and scan-free when the header survived:

```python
try:
    nxt = pos + zstd.get_frame_size(buf[pos:])   # exact, no decompression
except zstd.ZstdError:
    nxt = buf.find(MAGIC, pos + 4)               # header destroyed: fall back
if nxt != -1 and (nxt >= len(buf) or buf[nxt : nxt + 4] != MAGIC):
    nxt = -1                                     # reject an implausible size
```

Verified: `get_frame_size` returned the correct 21-byte size for a frame whose payload was
corrupted, so it resynchronises without decompressing and without a magic scan. This is
the one concrete capability `zstandard` cannot match; there, the magic-scan fallback is the
only option (and it is what the validated §5 implementation uses).

### 6c. Other notes

- **Checksumless frames + truncation-at-a-frame-boundary is indistinguishable from a
  clean stop**, but that is harmless: `eof=True` at a boundary advances correctly.
- **`decompressobj().decompress()` buffers a whole frame's output in memory.** Fine for
  JSONL batches; not a concern here.
- **`eof`/`unused_data` are the only stable contract.** Avoid the message strings and
  avoid `stream_reader` for offset math.

---

## Sources

Primary — executed against the installed libraries in CPython 3.12.7 (macOS arm64):
`zstandard` 0.25.0, `pyzstd` 0.19.1, `backports.zstd` 1.7.0; Homebrew `zstd` CLI 1.5.7.

- `zstandard` docstrings for `ZstdDecompressor.decompress` / `stream_reader`, shipped in
  `site-packages/zstandard/backend_cffi.py` (incl. the `read_across_frames` "not yet
  implemented" text) and the type stubs `zstandard/__init__.pyi`
  (`frame_content_size`, `frame_header_size`, `get_frame_parameters`, `FrameParameters`).
- `pyzstd/__init__.py` 0.19.1 — `from backports import zstd` / `from compression import
  zstd` dispatch that establishes pyzstd as a shim.
- `backports/zstd/__init__.py` 1.7.0 — `__all__` exposing `get_frame_size`,
  `get_frame_info`, `ZstdDecompressor`, `ZstdFile`, matching the stdlib module layout.
- PyPI JSON metadata (`https://pypi.org/pypi/<name>/json`) for versions, release dates,
  `requires_dist`, `requires_python` for all three packages.
- Wheel availability confirmed by `pip download --only-binary=:all: --platform
  macosx_11_0_arm64 --python-version 3.12` for each package.
- Reference semantics: `ai-usage/dsh-mongodb-usage-hook.mjs`, `frameStarts()` (line 88)
  and `decodeFrames()` (lines 108-142).
- Zstandard frame format and magic `0xFD2FB528` (RFC 8878), as implemented by the bundled
  zstd 1.5.7.
