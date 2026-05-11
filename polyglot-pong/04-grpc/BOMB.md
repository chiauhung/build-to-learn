# Bombs: break the gRPC contract on purpose

Same drill as previous versions. Add the line, regenerate stubs, run, watch what breaks, revert.

> v4's bombs are different in character. v1-v3 broke at runtime ("the bytes didn't parse"). v4 mostly breaks at **build time** — the codegen catches schema mistakes before they ever hit the wire. The ones that *do* reach runtime are sneakier, because the bytes look fine until you decode them with a different schema.

---

## 1. Forget to regenerate stubs after editing `.proto`

In `proto/ticker.proto`, rename a field:

```proto
message Metrics {
  string repo = 1;
  int32 stars = 2;
  int32 forks_this_week_NEW = 3;   // ← renamed but NOT renumbered
  int32 commits_today = 4;
  int32 open_issues = 5;
  string fetched_at = 6;
  int32 price = 7;
}
```

**Regenerate only the Python stubs** (skip `npm run gen`). Restart the server. From the client, `get vercel/next.js` still works — the bytes still decode correctly because the **field numbers** matched even though the names diverged.

**Lesson:** the wire contract is the **numbers**, not the names. As long as `= 3` means the same field on both sides, name skew is invisible to the wire (though painful for humans reading code). This is why you almost always want one git repo for both server and client, with a Makefile target that regenerates both.

---

## 2. Renumber a field (the silent corruption)

Now change `forks_this_week` to use a *different number*:

```proto
int32 forks_this_week = 99;   // ← was = 3
```

Regenerate **both sides**. Run. `get` returns `Metrics` with `forks_this_week = 0` — the server encoded into field `99`, the (newly regenerated) client decoded from field `99`, but if you had any *old* clients still running with the original stubs, they'd see `forks_this_week = 0` and never notice the bytes existed.

**Lesson:** Protobuf field numbers are **forever**. The compiler can't help across deploy generations — only careful PR review and the `reserved` keyword can. This is the #1 production gRPC footgun.

---

## 3. Skip the codegen step entirely

In `server/server.py`, delete the generated stub files (or just don't generate them). Run the server.

```
ModuleNotFoundError: No module named 'ticker_pb2'
```

Hard fail. No code runs.

**Lesson:** the generated files are part of your build, not your source. In a real project, codegen runs as a pre-commit hook or build step — every PR has fresh stubs. Treat `gen/` like `node_modules/` — never edit, never commit.

---

## 4. Wrong type in the `.proto`

Change `stars` from `int32` to `string`:

```proto
string stars = 2;
```

Regenerate Python. Restart server. The server now calls `ticker_pb2.Metrics(stars=139268, ...)` — runtime error:

```
TypeError: '139268' has type int, but expected string for field 'stars'
```

**Lesson:** Protobuf enforces types at the *boundary*. Your business logic might still have an int, but the moment you stuff it into a generated message, types must match. This is where the "schema enforces correctness" promise pays off — but only if you regenerate after every `.proto` change.

---

## 5. Server abort with the wrong status code

In `server.py`, replace the `GetPrice` handler's error path:

```python
except GitHubError as e:
    await context.abort(grpc.StatusCode.OK, str(e))   # ← OK?? for an error??
```

Client receives `status=OK, details=<error message>` — and treats it as success. The client never throws. The error becomes silent.

**Lesson:** gRPC `StatusCode` is the equivalent of HTTP status codes. Choose them carefully. Common ones: `INVALID_ARGUMENT` (bad input), `NOT_FOUND` (repo doesn't exist), `UNAVAILABLE` (GitHub down — retryable), `DEADLINE_EXCEEDED` (timeout), `INTERNAL` (your bug). Wrong code = wrong client behavior.

---

## 6. Forget to handle cancellation

In `StreamTicks`, remove the `if context.cancelled(): return` check:

```python
async def StreamTicks(self, request, context):
    queue = hub.queues[peer]
    while True:
        # if context.cancelled():
        #     return
        try:
            metrics_proto = await asyncio.wait_for(queue.get(), timeout=15)
            yield metrics_proto
        except asyncio.TimeoutError:
            continue
```

In the client, type `stream`, then `Ctrl+C` the client. Server keeps the streaming RPC alive forever — never knows the client is gone. Memory grows. Queue keeps filling.

**Lesson:** gRPC's `context` carries the cancellation signal. Long-running streaming methods must check it, or `await` something that surfaces it as `CancelledError`. WebSocket gets disconnect via exception; gRPC sometimes does too, but sometimes you must ask. Always ask in `while True:` loops.

---

## 7. Block the event loop (the recurring trap)

Replace `await asyncio.to_thread(fetch_repo_metrics, request.repo)` in `GetPrice` with the sync call:

```python
metrics = fetch_repo_metrics(request.repo)
```

In one terminal, `get` a slow repo. In another terminal client, `get` anything — it stalls until the first call finishes. **Every gRPC call on every connection stalls** because they all share the same asyncio event loop.

**Lesson:** same trap as v2 and v3. The async event loop has zero tolerance for sync I/O. gRPC adds no protection.

---

## 8. Truncate / corrupt the wire (debugging Protobuf is hard)

This one needs a small extra script. Make a fake "bad bytes" client:

```python
import grpc

async def bad():
    channel = grpc.aio.insecure_channel("127.0.0.1:50051")
    # Talk gRPC-shaped bytes but with wrong content
    await channel.unary_unary("/polyglot_pong.Ticker/Subscribe")(b"GARBAGE BYTES")
```

Server returns a generic INTERNAL error. You can't `curl` it. You can't see the bytes in DevTools. You need `grpcurl` or Wireshark with the Protobuf dissector to debug.

**Lesson:** binary Protobuf is much harder to debug than JSON. The trade-off for compactness and speed is opacity. Tooling helps (`grpcurl` is `curl` for gRPC) but you'll miss browser DevTools.

---

## 9. Concurrent subscribers, shared dict bug

In `Hub`, replace `defaultdict(asyncio.Queue)` with a single shared queue:

```python
class Hub:
    def __init__(self):
        self.watchlists = defaultdict(set)
        self.queue = asyncio.Queue()   # ← one queue for everyone
```

Then in `push`, write to `self.queue` directly. In `StreamTicks`, read from `self.queue`.

Open two clients, each `stream`. Whichever client happens to read first gets the tick. The other never sees it.

**Lesson:** same per-client-state bug as v2's BOMB experiment 7, in a different uniform. gRPC doesn't save you from logic bugs about who-gets-what.

---

## 10. The "I broke the proto file but didn't realize" failure

Open `proto/ticker.proto` and add a trailing comma where one shouldn't be, or break the syntax:

```proto
message Metrics {
  string repo = 1,    // ← comma instead of semicolon
  int32 stars = 2;
}
```

Try to regenerate. `protoc` exits with a clear parse error pointing at the line. No half-broken stubs are produced.

**Lesson:** Protobuf has a real parser with real syntax. Errors are early and clear — *if* you actually run codegen. The trap isn't broken syntax; it's broken *semantics* (renumbered fields, type changes) that parse fine but fail at runtime or on old clients.

---

# Recommended order (v4 mindblown path)

| # | Experiment              | What it teaches                                  |
| - | ----------------------- | ------------------------------------------------ |
| 1 | rename without regen    | wire is numbers, not names                       |
| 2 | renumber a field        | the #1 production gRPC footgun                   |
| 6 | forget cancellation     | streaming methods need active cleanup            |
| 5 | wrong status code       | gRPC codes drive client retry behavior           |
| 8 | corrupt wire bytes      | binary protocols are hard to debug — bring tools |

After these five, you'll feel why production gRPC teams have: shared monorepos for protos, codegen-as-CI-step, `reserved` discipline on every field deletion, gRPC interceptors for tracing/auth (instead of putting it in every method), and `grpcurl` permanently bookmarked.

The transition from "I know gRPC works" to "I know gRPC's failure modes" is exactly the gap the next project (multi-service + OTEL) needs you to have crossed first.
