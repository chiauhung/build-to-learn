"""
V4 SERVER: gRPC over HTTP/2 with Protobuf.
==========================================

Goal: Same domain, same methods, but the wire format is now binary
Protobuf and the transport is HTTP/2 multiplexed streams.

Read alongside v3's server.py. What's new:

  v3 (HTTP + SSE)                    v4 (gRPC)
  ───────────────────────────────────────────────────────────────────
  JSON envelope ({jsonrpc, id,...})  binary Protobuf messages
  text on the wire                   bytes on the wire
  POST /rpc + GET /events            one server, multiple typed methods
  session_id correlation             gRPC peer identity (per-connection)
  invent your own SSE format         streaming is built into the protocol
  client validates types at runtime  codegen enforces types at compile time

The .proto file (../proto/ticker.proto) is the contract. We run
`grpcio-tools` to generate ticker_pb2.py (messages) and
ticker_pb2_grpc.py (service stubs) — both consumed below. If you change
the .proto, you MUST regenerate before this file makes sense.

Generate the stubs (run from 04-grpc/):

    uv run python -m grpc_tools.protoc \\
        -Iproto \\
        --python_out=server \\
        --grpc_python_out=server \\
        proto/ticker.proto

Run:

    uv run python server/server.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import defaultdict
from concurrent import futures
from pathlib import Path

import grpc

# Make `shared/` importable. Same domain logic as every other version.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
from ticker_logic import GitHubError, fetch_repo_metrics, metrics_to_dict  # noqa: E402

# Make the generated stubs importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticker_pb2  # noqa: E402
import ticker_pb2_grpc  # noqa: E402

POLL_INTERVAL_SECONDS = 30


class Hub:
    """Per-client state, keyed by gRPC peer identity.

    In v1 there was one client; v2 keyed by WebSocket object; v3 keyed by
    session_id string. v4 keys by gRPC's built-in `peer()` — a string
    like "ipv4:127.0.0.1:54321" that uniquely identifies the connection.

    The asyncio.Event per peer is the signal channel between Subscribe()
    and StreamTicks() — when someone subscribes, we wake any active
    streaming RPC for that peer so it knows to add the new repo on its
    next iteration."""

    def __init__(self) -> None:
        self.watchlists: dict[str, set[str]] = defaultdict(set)
        # Per-peer queues of tick events ready to be streamed out.
        self.queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)

    def subscribe(self, peer: str, repo: str) -> list[str]:
        self.watchlists[peer].add(repo)
        return sorted(self.watchlists[peer])

    def unsubscribe(self, peer: str, repo: str) -> list[str]:
        self.watchlists[peer].discard(repo)
        return sorted(self.watchlists[peer])

    def watchlist(self, peer: str) -> list[str]:
        return sorted(self.watchlists.get(peer, set()))

    def all_subscribed_repos(self) -> set[str]:
        out: set[str] = set()
        for repos in self.watchlists.values():
            out |= repos
        return out

    def subscribers_of(self, repo: str) -> list[str]:
        return [peer for peer, repos in self.watchlists.items() if repo in repos]

    async def push(self, peer: str, metrics_proto: ticker_pb2.Metrics) -> None:
        await self.queues[peer].put(metrics_proto)

    def cleanup(self, peer: str) -> None:
        self.watchlists.pop(peer, None)
        self.queues.pop(peer, None)


hub = Hub()


def _metrics_to_proto(d: dict) -> ticker_pb2.Metrics:
    """Convert the shared `metrics_to_dict(...)` shape into the generated
    Protobuf Metrics message. Manual mapping is fine here — the dict
    schema is small and stable."""
    return ticker_pb2.Metrics(
        repo=d["repo"],
        stars=d["stars"],
        forks_this_week=d["forks_this_week"],
        commits_today=d["commits_today"],
        open_issues=d["open_issues"],
        fetched_at=d["fetched_at"],
        price=d["price"],
    )


class TickerServicer(ticker_pb2_grpc.TickerServicer):
    """Implements the four methods declared in ticker.proto.

    The base class (auto-generated) wires up gRPC routing. We override
    each method with the actual logic. Notice the method names match the
    .proto file exactly — codegen is doing the lookup."""

    async def Subscribe(
        self, request: ticker_pb2.SubscribeRequest, context: grpc.aio.ServicerContext
    ) -> ticker_pb2.Watchlist:
        peer = context.peer()
        repos = hub.subscribe(peer, request.repo)
        return ticker_pb2.Watchlist(repos=repos)

    async def Unsubscribe(
        self, request: ticker_pb2.UnsubscribeRequest, context: grpc.aio.ServicerContext
    ) -> ticker_pb2.Watchlist:
        peer = context.peer()
        repos = hub.unsubscribe(peer, request.repo)
        return ticker_pb2.Watchlist(repos=repos)

    async def List(
        self, request: ticker_pb2.ListRequest, context: grpc.aio.ServicerContext
    ) -> ticker_pb2.Watchlist:
        peer = context.peer()
        return ticker_pb2.Watchlist(repos=hub.watchlist(peer))

    async def GetPrice(
        self, request: ticker_pb2.GetPriceRequest, context: grpc.aio.ServicerContext
    ) -> ticker_pb2.Metrics:
        try:
            metrics = await asyncio.to_thread(fetch_repo_metrics, request.repo)
            return _metrics_to_proto(metrics_to_dict(metrics))
        except GitHubError as e:
            await context.abort(grpc.StatusCode.UNAVAILABLE, str(e))

    async def StreamTicks(
        self,
        request: ticker_pb2.StreamTicksRequest,
        context: grpc.aio.ServicerContext,
    ):
        """Server-streaming RPC. Replaces v1's `tick` notification and
        v3's SSE stream. This is one method on one connection — gRPC's
        HTTP/2 multiplexes it alongside other RPCs from the same client.

        The contract: the client calls this once after they've
        subscribed to some repos, and we yield a Metrics message for
        each tick that arrives in their per-peer queue."""
        peer = context.peer()
        queue = hub.queues[peer]
        try:
            while True:
                # context.cancel() fires when the client closes the stream.
                if context.cancelled():
                    return
                try:
                    metrics_proto = await asyncio.wait_for(queue.get(), timeout=15)
                    yield metrics_proto
                except asyncio.TimeoutError:
                    # No tick due — loop and check cancellation again.
                    # gRPC handles HTTP/2 PING frames for us, so no manual
                    # keepalive is required here.
                    continue
        finally:
            # The client's StreamTicks ended, but their watchlist may
            # still want to live (they could re-stream later). For this
            # demo we clean up everything — real apps would distinguish.
            hub.cleanup(peer)


async def poll_loop() -> None:
    """Same dedup/fanout idea as v2/v3. Difference: we push Protobuf
    Metrics messages onto per-peer queues instead of dict payloads."""
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        for repo in hub.all_subscribed_repos():
            peers = hub.subscribers_of(repo)
            if not peers:
                continue
            try:
                metrics = await asyncio.to_thread(fetch_repo_metrics, repo)
                proto = _metrics_to_proto(metrics_to_dict(metrics))
                for peer in peers:
                    await hub.push(peer, proto)
            except GitHubError as e:
                # gRPC has no concept of out-of-band server-push, so we
                # can't send `error` notifications the way SSE could. The
                # error surfaces on the next StreamTicks iteration as
                # a status code, or we just skip silently. For polish,
                # a real app would have a separate Notifications service
                # or a wrapper message type. We skip for now.
                print(f"[poll] {repo}: {e}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"[poll] {repo} unexpected: {e!r}", file=sys.stderr)


async def serve() -> None:
    server = grpc.aio.server()
    ticker_pb2_grpc.add_TickerServicer_to_server(TickerServicer(), server)
    listen_addr = "[::]:50051"
    server.add_insecure_port(listen_addr)

    asyncio.create_task(poll_loop())

    print(f"[server] gRPC ticker listening on {listen_addr}", file=sys.stderr)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
