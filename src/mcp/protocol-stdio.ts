import { Readable, Writable } from "node:stream";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { serializeMessage } from "@modelcontextprotocol/sdk/shared/stdio.js";
import type { JSONRPCMessage } from "@modelcontextprotocol/sdk/types.js";

/** Capture protocol writes before QMD can temporarily redirect process.stdout.write.
 * Native diagnostic writes still follow QMD's stderr redirect. Never replace it.
 */
export class ProtocolStdioServerTransport extends StdioServerTransport {
  private readonly protocolWrite: Writable["write"];
  private readonly output: Writable;
  private closed = false;
  private readonly pending = new Set<Promise<void>>();
  private readonly outputError = (error: Error) => { this.onerror?.(error); };

  constructor(input: Readable = process.stdin, output: Writable = process.stdout) {
    super(input, output);
    this.output = output;
    this.protocolWrite = output.write.bind(output);
    output.on("error", this.outputError);
  }

  override send(message: JSONRPCMessage): Promise<void> {
    // The callback waits for this write even when the stream applies backpressure.
    // Unlike a drain-only wait it also rejects failed writes instead of hanging.
    if (this.closed) return Promise.reject(new Error("protocol transport closed"));
    const sent = new Promise<void>((resolve, reject) => {
      this.protocolWrite(serializeMessage(message), (error?: Error | null) => {
        if (error) reject(error); else resolve();
      });
    });
    this.pending.add(sent);
    void sent.then(() => this.pending.delete(sent), () => this.pending.delete(sent));
    return sent;
  }

  override async close(): Promise<void> {
    this.closed = true;
    try { await super.close(); }
    finally {
      await Promise.allSettled([...this.pending]);
      // Node emits stream errors after write callbacks; retain the listener
      // through that turn, including close during an outstanding failed write.
      await new Promise<void>(resolve => setImmediate(resolve));
      this.output.off("error", this.outputError);
    }
  }
}
