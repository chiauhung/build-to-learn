# Bombs: break the protocol on purpose

You don't really learn IPC by reading code — you learn it by **breaking it once with your own hands**. Each experiment below is a tiny edit that exposes one real-world failure mode. Add the line, run `npx tsx host.ts`, watch what breaks, then revert.

> Keep the waiter/kitchen analogy from [NOTES.md](NOTES.md) in mind — most of these failures are "the waiter and kitchen stopped agreeing on what's on the slip vs. what's just chatter."

---

## 1. Stdout protocol corruption

**Edit** `worker.py`:

```python
def _do_list() -> dict:
    print("HELLO DEBUG")          # ← rogue stdout write
    with _lock:
        return {"watchlist": sorted(_watchlist)}
```

Type `list` at the prompt. The host's parser breaks or hangs — because stdout now looks like:

```
HELLO DEBUG
Content-Length: 52\r\n\r\n{"jsonrpc":"2.0"...}
```

TS expects `Content-Length:` at the start of every frame. A stray `print()` is the chef yelling into the kitchen window and confusing the waiter into thinking it's an order.

**Lesson:** stdout is the **protocol channel**, not a debug channel. This is why `print(..., file=sys.stderr)` exists.

---

## 2. Stderr is safe (the fix)

Change the line to:

```python
print("HELLO DEBUG", file=sys.stderr)
```

Now you see the log, protocol still works. `stderr` is the back-of-house intercom — chatter the customer never sees.

| stream | role    |
| ------ | ------- |
| stdout | machine |
| stderr | human   |

---

## 3. Remove flush() → mystery hangs

In `_write_frame()`, delete `sys.stdout.buffer.flush()`. Requests now hang or arrive in delayed bursts.

**Why:** `write()` only puts bytes into Python's stdout buffer; it's not in the pipe until you flush. The bytes are sitting in memory, the waiter is staring at an empty window.

**Lesson:** local IPC has buffering too — not just networks.

---

## 4. Partial frame (split write)

In `host.ts`, replace the single `write` with a delayed split:

```ts
this.child.stdin.write(header);
setTimeout(() => this.child.stdin.write(body), 3000);
```

**Result:** still works after the 3s delay. Python's blocking `read(N)` patiently waits for the rest.

**Lesson:** streams arrive **gradually**. "One message = one receive" is the illusion framing gives you, not the reality.

---

## 5. Two frames in one chunk

In `host.ts`, send two framed messages back-to-back in a single `write`:

```ts
this.child.stdin.write(Buffer.concat([header1, body1, header2, body2]));
```

**Result:** still works. `_read_frame()` consumes exactly one frame; the rest sits in stdin's buffer until the next read.

**Lesson:** chunk boundaries ≠ message boundaries. The framing is what carves the stream into messages.

---

## 6. Lying Content-Length

In `host.ts`, hardcode a header way too big:

```ts
const header = Buffer.from(`Content-Length: 999999\r\n\r\n`, "ascii");
```

Worker hangs forever on `read(999999)`. Whole system frozen.

**Lesson:** corrupt protocol **metadata** poisons the entire stream. The waiter can recover from a wrong dish; can't recover from "this slip says 999999 characters" when only 50 arrive.

---

## 7. Remove the lock → interleaved frames

In `_write_frame()`, delete the `with _lock:` block. Subscribe to a few repos and wait for ticks.

Sometimes you'll see garbled output like:

```
Content-LenContent-Length: 87...
```

Two threads (request handler + poll loop) both wrote to stdout simultaneously. Bytes interleaved at the OS level — stdout is **not** atomic.

**Lesson:** this is the same race condition you'd hit in any concurrent distributed system. Locks aren't a Python thing; they're a "multiple writers, one shared resource" thing.

---

## 8. Backpressure (spam ticks)

Replace the poll loop body with:

```python
while True:
    _notify("tick", {"x": "A" * 100000})
```

Worker eventually freezes. The pipe buffer (typically 64KB on macOS) fills up because the host can't read fast enough, so `write()` blocks.

**Lesson:** **backpressure exists everywhere**, even between two processes on the same machine. If you don't drain, the producer stalls.

---

## 9. Malformed JSON

In `host.ts`, send garbage as the body:

```ts
const body = Buffer.from("{BROKEN JSON");
```

Worker's `json.loads()` raises. Whether the worker survives depends on your error handling — try it both with and without the existing `try/except` around `_read_frame()`.

**Lesson:** every protocol boundary needs a defensive parser. The waiter shouldn't quit if one slip is gibberish.

---

# Recommended order (beginner mindblown path)

| # | Experiment              | What it teaches                          |
| - | ----------------------- | ---------------------------------------- |
| 1 | stdout corruption       | stdout is sacred                         |
| 2 | stderr is safe          | the fix — and why two streams exist      |
| 3 | remove flush            | local IPC has buffers                    |
| 4 | partial frame           | streams are gradual                      |
| 7 | remove lock             | concurrency = locks, not language        |

After these five, you'll feel the OS pipe + protocol layer in your bones. Experiments 5/6/8/9 are bonus rounds covering edge cases you'll meet later in WS and SSE versions too.
