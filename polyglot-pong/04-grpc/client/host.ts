/**
 * V4 CLIENT: TS Node CLI talking gRPC to the Python server.
 * =========================================================
 *
 * Mirrors v1's host.ts setup (TS CLI ↔ Python server) but the wire is
 * binary Protobuf over HTTP/2 instead of length-prefixed JSON over stdio.
 *
 * Things that disappear vs v1/v2/v3:
 *   - No manual framing. HTTP/2 streams handle it.
 *   - No request id correlation. gRPC's Call object is the correlation.
 *   - No "did we send all the bytes?" — protobuf serialization is atomic.
 *   - No "is this a notification or a response?" — server-streaming has
 *     a typed method shape that says "many responses are coming."
 *
 * Things that appear vs v1/v2/v3:
 *   - A separate codegen step before you can compile (`npm run gen`).
 *   - Method names and message types live in generated files, not strings.
 *   - You think in terms of "call this method on this stub," not "send
 *     this message over this connection."
 *
 * Run (from 04-grpc/client/):
 *
 *     npm install
 *     npm run gen          # generates gen/ticker_pb.js and ticker_grpc_pb.js
 *     npm start            # runs this file
 */

import * as readline from "node:readline";
import * as grpc from "@grpc/grpc-js";
import { resolve } from "node:path";

// Generated stubs. These don't exist until you run `npm run gen`.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const services = require(resolve(__dirname, "gen/ticker_grpc_pb.js"));
// eslint-disable-next-line @typescript-eslint/no-require-imports
const messages = require(resolve(__dirname, "gen/ticker_pb.js"));

const SERVER_ADDR = "127.0.0.1:50051";

// Build a client stub. The stub knows every method on the Ticker service.
// This is the heart of gRPC: the stub looks like a local object but every
// method call serializes args, opens an HTTP/2 stream, and gets a response.
const client = new services.TickerClient(SERVER_ADDR, grpc.credentials.createInsecure());

function fmtMetrics(m: any): string {
  const ts = (m.getFetchedAt() ?? "").slice(11, 19);
  return `[${ts}] ${m.getRepo().padEnd(28)} price=${String(m.getPrice()).padStart(8)} ` +
    `★${m.getStars()} fork7d=${m.getForksThisWeek()} commitsToday=${m.getCommitsToday()} ` +
    `issues=${m.getOpenIssues()}`;
}

function fmtWatchlist(w: any): string {
  return `watchlist: [${w.getReposList().join(", ")}]`;
}

// Promisify a unary call — gRPC's JS callback API is verbose.
function callUnary<TReq, TRes>(
  method: (req: TReq, cb: (err: any, res: TRes) => void) => void,
  req: TReq,
): Promise<TRes> {
  return new Promise((resolveFn, rejectFn) => {
    method.call(client, req, (err: any, res: TRes) => {
      if (err) rejectFn(err);
      else resolveFn(res);
    });
  });
}

// Server-streaming call. The returned object emits 'data' for each
// streamed Metrics message and 'end' when the server closes the stream.
let activeStream: any = null;

function startTickStream(): void {
  if (activeStream) {
    console.log("[stream already active]");
    return;
  }
  const req = new messages.StreamTicksRequest();
  activeStream = client.streamTicks(req);
  activeStream.on("data", (m: any) => console.log(fmtMetrics(m)));
  activeStream.on("error", (e: any) => {
    console.error(`[stream error] ${e.message}`);
    activeStream = null;
  });
  activeStream.on("end", () => {
    console.log("[stream ended]");
    activeStream = null;
  });
  console.log("[stream started — ticks will appear as they fire]");
}

function stopTickStream(): void {
  if (!activeStream) {
    console.log("[no active stream]");
    return;
  }
  activeStream.cancel();
  activeStream = null;
}

async function main(): Promise<void> {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  rl.setPrompt("pong-grpc> ");
  rl.prompt();

  rl.on("line", async (raw) => {
    const line = raw.trim();
    if (!line) return rl.prompt();
    const [cmd, ...rest] = line.split(/\s+/);
    const arg = rest.join(" ");

    try {
      switch (cmd) {
        case "subscribe":
        case "sub": {
          const req = new messages.SubscribeRequest();
          req.setRepo(arg);
          const res = await callUnary(client.subscribe, req);
          console.log(fmtWatchlist(res));
          break;
        }
        case "unsubscribe":
        case "unsub": {
          const req = new messages.UnsubscribeRequest();
          req.setRepo(arg);
          const res = await callUnary(client.unsubscribe, req);
          console.log(fmtWatchlist(res));
          break;
        }
        case "list":
        case "ls": {
          const req = new messages.ListRequest();
          const res = await callUnary(client.list, req);
          console.log(fmtWatchlist(res));
          break;
        }
        case "get": {
          const req = new messages.GetPriceRequest();
          req.setRepo(arg);
          const res = await callUnary(client.getPrice, req);
          console.log(fmtMetrics(res));
          break;
        }
        case "stream":
          startTickStream();
          break;
        case "stop":
          stopTickStream();
          break;
        case "quit":
        case "exit":
          if (activeStream) activeStream.cancel();
          rl.close();
          return;
        default:
          console.log(
            "commands: subscribe <repo> | unsubscribe <repo> | list | get <repo> | " +
            "stream | stop | quit",
          );
      }
    } catch (e) {
      console.error(`error: ${(e as Error).message}`);
    }
    rl.prompt();
  });

  rl.on("close", () => {
    client.close();
    process.exit(0);
  });
}

main();
