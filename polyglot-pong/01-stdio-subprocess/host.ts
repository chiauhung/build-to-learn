/**
 * V1 HOST: TS/Node spawning the Python worker over stdio.
 * =======================================================
 *
 * Goal: Be the "editor" that an LSP server lives inside, or the "Claude
 * client" that an MCP stdio server lives inside. We:
 *   - spawn worker.py as a child process
 *   - frame JSON-RPC requests with Content-Length headers
 *   - read framed responses and notifications back from its stdout
 *   - pipe its stderr through to ours so worker logs are visible
 *
 * The whole protocol layer is ~50 lines. That's the lesson — once you've
 * written it once, MCP and LSP stop feeling like magic.
 *
 * Run (no deps; uses Node's built-in --experimental-strip-types or tsx):
 *
 *     node --experimental-strip-types host.ts
 *     # or
 *     npx tsx host.ts
 *
 * Then type at the prompt:
 *     subscribe vercel/next.js
 *     subscribe facebook/react
 *     list
 *     get vercel/next.js
 *     unsubscribe vercel/next.js
 *     quit
 */

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import * as readline from "node:readline";
import { resolve } from "node:path";

type RpcId = number;
type Pending = {
  resolve: (v: unknown) => void;
  reject: (e: Error) => void;
};

class StdioRpcClient {
  private child: ChildProcessWithoutNullStreams;
  private buf: Buffer = Buffer.alloc(0);
  private nextId: RpcId = 1;
  private pending = new Map<RpcId, Pending>();
  private onNotify: (method: string, params: unknown) => void;

  constructor(
    cmd: string,
    args: string[],
    onNotify: (method: string, params: unknown) => void,
  ) {
    this.onNotify = onNotify;
    this.child = spawn(cmd, args, { stdio: ["pipe", "pipe", "pipe"] });
    this.child.stdout.on("data", (chunk: Buffer) => this.onStdout(chunk));
    this.child.stderr.on("data", (chunk: Buffer) =>
      process.stderr.write(chunk),
    );
    this.child.on("exit", (code) => {
      for (const p of this.pending.values()) {
        p.reject(new Error(`worker exited with code ${code}`));
      }
      this.pending.clear();
    });
  }

  /**
   * Send a JSON-RPC request and resolve when the matching response comes
   * back. The id is how we correlate request → response across an
   * out-of-order stream of notifications.
   */
  request(method: string, params: object = {}): Promise<unknown> {
    const id = this.nextId++;
    const msg = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolveFn, rejectFn) => {
      this.pending.set(id, { resolve: resolveFn, reject: rejectFn });
      this.writeFrame(msg);
    });
  }

  close(): void {
    this.child.stdin.end();
  }

  // ---- framing ----

  private writeFrame(msg: object): void {
    const body = Buffer.from(JSON.stringify(msg), "utf-8");
    const header = Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, "ascii");
    this.child.stdin.write(Buffer.concat([header, body]));
  }

  /**
   * Streaming parser. TCP/pipes don't preserve message boundaries — one
   * 'data' event can contain half a message, two messages, or anything in
   * between. We accumulate bytes in `buf` and pull out complete frames as
   * the headers + body become available.
   */
  private onStdout(chunk: Buffer): void {
    this.buf = Buffer.concat([this.buf, chunk]);
    while (true) {
      const headerEnd = this.buf.indexOf("\r\n\r\n");
      if (headerEnd === -1) return; // headers not complete yet

      const headerText = this.buf.subarray(0, headerEnd).toString("ascii");
      const match = /Content-Length:\s*(\d+)/i.exec(headerText);
      if (!match) {
        // Bad frame — drop bytes up to the header terminator and resync.
        this.buf = this.buf.subarray(headerEnd + 4);
        continue;
      }
      const bodyLen = parseInt(match[1], 10);
      const totalLen = headerEnd + 4 + bodyLen;
      if (this.buf.length < totalLen) return; // body not complete yet

      const body = this.buf.subarray(headerEnd + 4, totalLen);
      this.buf = this.buf.subarray(totalLen);
      this.dispatch(JSON.parse(body.toString("utf-8")));
    }
  }

  private dispatch(msg: any): void {
    // Notification: has `method`, no `id`.
    if (msg.method && msg.id === undefined) {
      this.onNotify(msg.method, msg.params);
      return;
    }
    // Response: has `id`.
    const p = this.pending.get(msg.id);
    if (!p) return;
    this.pending.delete(msg.id);
    if (msg.error) p.reject(new Error(`${msg.error.code}: ${msg.error.message}`));
    else p.resolve(msg.result);
  }
}

// ---- pretty printing ----

function fmtTick(m: any): string {
  const ts = (m.fetched_at ?? "").slice(11, 19); // HH:MM:SS
  return `[${ts}] ${m.repo.padEnd(28)} price=${String(m.price).padStart(8)} ` +
    `★${m.stars} fork7d=${m.forks_this_week} commitsToday=${m.commits_today} ` +
    `issues=${m.open_issues}`;
}

// ---- REPL ----

async function main(): Promise<void> {
  const workerPath = resolve(__dirname, "worker.py");
  const client = new StdioRpcClient("python3", [workerPath], (method, params: any) => {
    if (method === "tick") console.log(fmtTick(params));
    else if (method === "error") console.error(`[worker error] ${params?.repo ?? ""} ${params?.message}`);
    else console.log(`[notif:${method}]`, params);
  });

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  rl.setPrompt("pong> ");
  rl.prompt();

  rl.on("line", async (raw) => {
    const line = raw.trim();
    if (!line) return rl.prompt();
    const [cmd, ...rest] = line.split(/\s+/);
    const arg = rest.join(" ");
    try {
      switch (cmd) {
        case "subscribe":
        case "sub":
          console.log(await client.request("subscribe", { repo: arg }));
          break;
        case "unsubscribe":
        case "unsub":
          console.log(await client.request("unsubscribe", { repo: arg }));
          break;
        case "list":
        case "ls":
          console.log(await client.request("list"));
          break;
        case "get":
          console.log(fmtTick(await client.request("get_price", { repo: arg })));
          break;
        case "quit":
        case "exit":
          rl.close();
          return;
        default:
          console.log("commands: subscribe <repo> | unsubscribe <repo> | list | get <repo> | quit");
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
