"""
V1 WORKER: Python daemon talking JSON-RPC over stdio.
=====================================================

Goal: Be the "kernel" that the TS host spawns. We:
  - read length-prefixed JSON-RPC frames from stdin
  - dispatch methods (subscribe / unsubscribe / get_price / list)
  - poll GitHub on a timer in a background thread
  - push `tick` notifications to stdout

This is exactly how an LSP server, an MCP stdio server, or a Jupyter kernel
works. No ports, no auth, no network — just OS pipes between two processes.

Framing: LSP/JSON-RPC style. Each message is:

    Content-Length: <byte length>\\r\\n
    \\r\\n
    {"jsonrpc":"2.0", ...}

Why length-prefixed and not newline-delimited? Because JSON can contain
newlines inside strings. Length prefixes are the standard fix; reading
until \\n only works if you control every character that goes into the
payload, and you usually don't.

Run (normally invoked by host.ts, but also runnable standalone for debug):

    python worker.py
    # then paste a frame on stdin:
    Content-Length: 65
    \\r\\n
    {"jsonrpc":"2.0","id":1,"method":"get_price","params":{"repo":"vercel/next.js"}}
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

# Make `shared/` importable. Each transport version lives in its own folder
# but reuses the domain logic — see ../shared/ticker_logic.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from ticker_logic import GitHubError, fetch_repo_metrics, metrics_to_dict  # noqa: E402

POLL_INTERVAL_SECONDS = 30

# Lock guards both stdout writes (frames must not interleave) AND the
# watchlist (read by the polling thread, mutated by the request thread).
_lock = threading.Lock()
_watchlist: set[str] = set()


# ---------- framing ----------

def _read_frame() -> dict | None:
    """Read one Content-Length-framed JSON-RPC message from stdin.

    Returns None on EOF (host closed the pipe → we should exit).
    """
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None  # EOF
        if line in (b"\r\n", b"\n"):
            break  # blank line ends headers
        key, _, value = line.decode().partition(":")
        headers[key.strip().lower()] = value.strip()

    length = int(headers["content-length"])
    payload = sys.stdin.buffer.read(length)
    return json.loads(payload)


def _write_frame(msg: dict) -> None:
    """Send one Content-Length-framed message to stdout. Thread-safe."""
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    with _lock:
        sys.stdout.buffer.write(header + body)
        sys.stdout.buffer.flush()


def _log(msg: str) -> None:
    """Worker-side debug log goes to stderr so it doesn't corrupt the
    framed protocol on stdout. The host can choose to print or hide it."""
    print(f"[worker] {msg}", file=sys.stderr, flush=True)


# ---------- JSON-RPC responses ----------

def _ok(req_id, result) -> None:
    _write_frame({"jsonrpc": "2.0", "id": req_id, "result": result})


def _err(req_id, code: int, message: str) -> None:
    _write_frame(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    )


def _notify(method: str, params: dict) -> None:
    """Server → client push. Notifications have no `id`."""
    _write_frame({"jsonrpc": "2.0", "method": method, "params": params})


# ---------- methods ----------

def _do_subscribe(repo: str) -> dict:
    with _lock:
        _watchlist.add(repo)
        return {"watchlist": sorted(_watchlist)}


def _do_unsubscribe(repo: str) -> dict:
    with _lock:
        _watchlist.discard(repo)
        return {"watchlist": sorted(_watchlist)}


def _do_list() -> dict:
    with _lock:
        return {"watchlist": sorted(_watchlist)}


def _do_get_price(repo: str) -> dict:
    return metrics_to_dict(fetch_repo_metrics(repo))


# ---------- background poller ----------

def _poll_loop() -> None:
    """Every POLL_INTERVAL_SECONDS, fetch each subscribed repo and push a tick.

    Runs in a daemon thread so it dies with the process. We snapshot the
    watchlist under the lock, then release it before doing slow network
    calls — otherwise subscribe/unsubscribe would block on HTTP latency.
    """
    while True:
        time.sleep(POLL_INTERVAL_SECONDS)
        with _lock:
            snapshot = list(_watchlist)
        for repo in snapshot:
            try:
                m = fetch_repo_metrics(repo)
                _notify("tick", metrics_to_dict(m))
            except GitHubError as e:
                _notify("error", {"repo": repo, "message": str(e)})
            except Exception as e:  # noqa: BLE001
                _notify("error", {"repo": repo, "message": f"unexpected: {e!r}"})


# ---------- main loop ----------

METHODS = {
    "subscribe": lambda p: _do_subscribe(p["repo"]),
    "unsubscribe": lambda p: _do_unsubscribe(p["repo"]),
    "list": lambda p: _do_list(),
    "get_price": lambda p: _do_get_price(p["repo"]),
}


def main() -> None:
    _log(f"started pid={os.getpid()} poll={POLL_INTERVAL_SECONDS}s")
    threading.Thread(target=_poll_loop, daemon=True).start()

    while True:
        try:
            msg = _read_frame()
        except Exception as e:  # malformed frame — log and keep going
            _log(f"frame read failed: {e!r}")
            continue
        if msg is None:
            _log("stdin EOF, exiting")
            return

        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        if method not in METHODS:
            _err(req_id, -32601, f"method not found: {method}")
            continue

        try:
            result = METHODS[method](params)
            _ok(req_id, result)
        except GitHubError as e:
            _err(req_id, -32000, str(e))
        except KeyError as e:
            _err(req_id, -32602, f"missing param: {e}")
        except Exception as e:  # noqa: BLE001
            _log(f"unhandled: {traceback.format_exc()}")
            _err(req_id, -32603, f"internal error: {e!r}")


if __name__ == "__main__":
    main()
