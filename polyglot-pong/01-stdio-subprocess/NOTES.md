# Notes: host ↔ worker as a mirror

Both sides are doing the same job — one sends requests, one handles them. Read the tables top-to-bottom and you'll see every TS concept has a Python mirror.

**Analogy:** think of it like a *waiter and a kitchen*.

- The TS host is the waiter — takes orders from the customer (REPL), writes them on a slip with a ticket number, hands them through the window, waits for plates to come back, also picks up surprise dishes the kitchen sends out on its own (the chef's specials = `tick` notifications).
- The Python worker is the kitchen — reads tickets off the window, cooks, sends plates back with the matching ticket number, and occasionally pushes out specials nobody ordered.
- The **window** (stdin/stdout pipe) is the only way they communicate. Neither side can see the other directly.

---

# Role overview

| TS Host              | Python Worker     |
| -------------------- | ----------------- |
| client               | server            |
| spawn child process  | gets spawned      |
| send request         | handle request    |
| wait response        | return response   |
| receive notification | push notification |
| interactive REPL     | background daemon |

---

# Process startup

Like the restaurant opening — the waiter unlocks the door (`spawn`), and the kitchen staff clock in (`main()`).

| TS                                | Python                              |
| --------------------------------- | ----------------------------------- |
| `spawn(cmd, args)`                | `if __name__ == "__main__": main()` |
| start child process               | process gets started                |
| `stdio: ["pipe", "pipe", "pipe"]` | `sys.stdin / stdout / stderr`       |

---

# The pipes (the kitchen window)

| TS                            | Python                         |
| ----------------------------- | ------------------------------ |
| `child.stdin.write(...)`      | `sys.stdin.buffer.read(...)`   |
| `child.stdout.on("data")`     | `sys.stdout.buffer.write(...)` |
| `process.stderr.write(chunk)` | `print(..., file=sys.stderr)`  |

`stderr` is the **back-of-house intercom** — the chef can shout "we're out of tomatoes!" without it ending up on a customer's plate. That's why worker logs go to stderr: they won't corrupt the framed protocol on stdout.

---

# Framing (the order slips)

The most important section.

| TS Host                         | Python Worker          |
| ------------------------------- | ---------------------- |
| `writeFrame()`                  | `_read_frame()`        |
| `Content-Length` header         | parse `Content-Length` |
| `Buffer.concat([header, body])` | `read(length)`         |
| send framed message             | receive framed message |

**Analogy:** imagine the waiter shouts orders through the window instead of writing slips. "TWO BURGERS NO PICKLES MEDIUM RARE FRIES ON THE SIDE TABLE FOUR." The kitchen has no idea where one order ends and the next begins. Solution: **every order is on a slip that starts with "this slip is 47 characters long."** The kitchen reads exactly 47 characters, knows it has one complete order, and moves on. That's `Content-Length`.

Why not just use newlines as separators? Because the order itself might contain a newline (a JSON string with `\n` in it). Length prefix is bulletproof; newlines aren't.

---

# Send request

| TS Host                | Python Worker               |
| ---------------------- | --------------------------- |
| `client.request()`     | `METHODS[method]`           |
| build JSON-RPC request | dispatch request            |
| `{id, method, params}` | read `{id, method, params}` |
| wait Promise           | execute handler             |

---

# Response correlation (the ticket number)

This is what makes it RPC instead of just message passing.

| TS Host                | Python Worker            |
| ---------------------- | ------------------------ |
| `nextId++`             | `req_id = msg.get("id")` |
| `pending.set(id, ...)` | `_ok(req_id, result)`    |
| match response by id   | return same id           |

**Analogy:** a busy waiter sends three orders to the kitchen back-to-back. Plates come back in a different order than they were sent. How does the waiter know which plate belongs to which table? Every slip has a **ticket number**, and the plate comes back with the same number on it. That's the `id` field.

Without ticket numbers, you'd have to send one order, wait for it, then send the next — no concurrency. With ticket numbers, you can have many requests in flight at once and still match them up correctly.

---

# JSON-RPC response

| TS Host         | Python Worker     |
| --------------- | ----------------- |
| `dispatch(msg)` | `_ok()`           |
| `msg.result`    | `{"result": ...}` |
| `msg.error`     | `_err()`          |

---

# Notifications (the chef's specials)

A `tick` or `error` isn't a reply to anything — it's the kitchen pushing food out unprompted. The waiter recognizes them because they have **no ticket number** (`id` is missing).

| TS Host                    | Python Worker             |
| -------------------------- | ------------------------- |
| `onNotify(method, params)` | `_notify(method, params)` |
| receive server push        | send server push          |
| no `id`                    | no `id`                   |

This is exactly how WebSocket server-push or SSE events feel later — same pattern, different transport.

---

# Tick flow

```
Python background thread (chef on a 30s timer)
    ↓
_notify("tick")        ← chef plates a special
    ↓
stdout pipe            ← passes it through the window
    ↓
TS onStdout()          ← waiter sees something arrived
    ↓
dispatch()             ← reads the slip
    ↓
onNotify()             ← no ticket number → it's a special, hand it to the customer
```

---

# The one asymmetry: buffering

This is the *one* place where the host/worker symmetry breaks — and it's worth understanding why, because it's not a language preference, it's a fundamental I/O-model difference.

```
Node (TS):
  one 'data' event = arbitrary bytes
  ─ could be ½ a frame, 2 frames, 1.5 frames…
  ─ must accumulate in a Buffer and pull complete frames out manually
  ─ this is what onStdout() does with this.buf

Python:
  sys.stdin.buffer.read(N) blocks until exactly N bytes arrive
  ─ no buffering logic needed
  ─ the OS does the waiting for you
  ─ this is why _read_frame() looks so much simpler
```

**Analogy:** imagine two waiters at the kitchen window.

- The **Python waiter** is patient. When the chef says "I need 47 characters," the waiter stands there silently until exactly 47 characters arrive, then walks away with a complete slip. Boring but correct.
- The **TS waiter** is hyperactive — every time *any* bytes come through the window, he has to act *right now*. So he keeps a clipboard. Bytes arrive: clip them. Check if he has a full header yet. If yes, check Content-Length. If he has enough bytes, peel off one slip and process it. Then check again — maybe he has another full slip on the clipboard. Loop until he doesn't.

The clipboard is `this.buf`. The reason Node forces you to do this is its **event loop**: it can't block, so it surfaces "some bytes arrived" events with no guarantee about message boundaries. Python's blocking `read(N)` lets the OS handle that for you.

This asymmetry shows up *every* time you cross between event-loop and blocking-I/O worlds. It's not a TS quirk — it's the price of async.

---

# Concurrency

| TS Host             | Python Worker  |
| ------------------- | -------------- |
| event loop          | thread         |
| `stdout.on("data")` | `_poll_loop()` |
| async Promise       | daemon thread  |

The waiter handles many tables by being fast and never sitting down (event loop). The kitchen handles many things at once by having multiple cooks (threads). Different strategies, same goal: don't block on slow work.

---

# Request handling

| TS Host             | Python Worker     |
| ------------------- | ----------------- |
| user types command  | server dispatches |
| `subscribe foo/bar` | `"subscribe"`     |
| `get foo/bar`       | `"get_price"`     |

---

# Error handling

| TS Host            | Python Worker        |
| ------------------ | -------------------- |
| `Promise.reject()` | `_err()`             |
| `try/catch`        | `except Exception`   |
| print error        | JSON-RPC error frame |

A failed order doesn't break the kitchen — the chef writes "86 the salmon" on the slip and sends it back with the original ticket number. The waiter pairs it with the right table and apologizes. The restaurant keeps running.

---

# What you've actually built

If you understood `host.ts ↔ worker.py`, you've understood the architecture of every row in this table — only the framing differs:

| Real System            | Maps to   |
| ---------------------- | --------- |
| VSCode                 | TS host   |
| Python language server | worker.py |
| Claude Desktop         | host      |
| MCP server             | worker    |
| Jupyter frontend       | host      |
| Jupyter kernel         | worker    |

Same restaurant, different cuisines.

---

# The universal pattern

Everything you're learning lately —

- tRPC
- gRPC
- MCP
- OTEL
- agents
- distributed systems

— is the same four-ingredient recipe:

```
message passing
+
contracts / schema
+
transport
+
correlation
```

Only the **transport** changes:

| System    | Transport        |
| --------- | ---------------- |
| REST      | HTTP             |
| gRPC      | HTTP/2           |
| MCP stdio | stdin/stdout     |
| WebSocket | TCP              |
| Kafka     | log/event stream |

Once you've felt the four ingredients in this 200-line project, every fancier system above stops being magic. It's all variations on the same restaurant — the waiter, the kitchen, the window, the ticket numbers.
