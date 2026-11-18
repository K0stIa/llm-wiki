# Experimental trusted host journal (partial G1 only)

`host_journal.Journal` is an explicit opt-in **trusted launcher library**, not a
model tool, MCP request handler, or production host adapter. Existing transports
are unchanged. Do not expose enrollment, session/call identifiers, epoch, journal
path, endpoint, or scope as model-controlled arguments.

The launcher must authenticate and bind project + worker principal + current
restore epoch, and verify the Unix service endpoint belongs to that same scope.
The new read-only `wiki_host_binding` handshake checks live project/principal/
epoch before each execute. `wiki_host_propose` passes the enrolled expected epoch,
checked inside the authority's SQLite mutation transaction. Cached receipts also
require an extant nonfailed operation and a second live binding check. Restored
instances reject old prepared requests without minting another key. Socket server
authenticity still depends on trusted launcher filesystem/mount isolation; this
is not a cryptographic endpoint attestation. Actual host G1 is NOT closed.

Explicit first enrollment: `Journal.enroll(path, project=..., principal='worker',
epoch=...)`. Store this journal in trusted durable host storage, outside worker
mounts. Existing paths are rejected; missing journals on normal restart fail
closed. Never automatically enroll a replacement after loss, corruption, restore,
or scope mismatch. Such recovery needs reconciliation against authority records.

Construct with the identical scope, then `execute(verified_socket, stable_session,
stable_call, model_args_without_key)`. Stable identity must come from a durable
host run/call ledger OUTSIDE the model payload. A JSON-RPC request number is not
sufficient unless the host explicitly guarantees its durable semantics.

**Pi adapter (2026-11-15).** With `WIKI_JOURNAL` set to an enrolled journal,
`src/pi/wiki-mcp-extension.ts` registers a native `wiki_propose` tool
(`src/pi/wiki-journal.ts`) keyed by Pi's `ctx.sessionManager.getSessionId()`
and `toolCallId`. It runs `journal_rpc.py recover` on `session_start` before new
calls, and launches the MCP server in `journaled` mode, which exposes no
unjournaled `wiki_propose`. `journal_rpc.py` transports through the one-shot
worker authority RPC instead of the experimental socket. Enrollment is explicit:
`echo '{"op":"enroll"}' | python3 src/mcp/journal_rpc.py JOURNAL DATABASE PROJECT`.
`tests/runtime/journal-adapter.test.mjs` drives the adapter code with named crash
points. Not yet verified in a live Pi session: that Pi persists the tool call id
before execution, and that pi-subagents children receive the native tool through
`tools: ["wiki_propose"]`. Codex, Claude Code and OpenCode adapters are not integrated.

`prepare` durably commits one deterministic operation key and canonical immutable
payload before sending. Retries with the same identity return the exact saved
request; changed payload or scope is denied. No new key is issued after epoch
mismatch or an authority error. `execute` saves the full receipt after transport.
Lost responses replay the persisted request and rely on authority idempotency.
Concurrent callers share SQLite serialized preparation and receipt comparison.
The separate low-level `send` API exists for trusted transport/testing, not model
use. Malicious trusted code or same-user filesystem modification is out of scope.

Durability: SQLite FULL synchronous with rollback journal and directory fsync on
initial enrollment. No proof against hardware lying about fsync, storage loss,
or rollback of both authority and journal without an epoch change. No arbitrary
storage-rollback detection; supported restore creates a fresh epoch.
Bounded tests use disposable real SQLite authority + worker Unix service and
SIGKILL/restart before send and after authority commit/before local receipt;
recovery produces one proposal and exact stable receipt. Actual online backup/
clean-instance restore rejects cached and prepared pre-restore calls. A missing
live operation also rejects a cached receipt. No models/network.

Keys hash the versioned canonical project/principal/epoch/session/call identity;
payload is intentionally excluded. If a stale journal loses a row within the same
authority epoch, the same stable call identity regenerates the SAME key, and the
authority rejects a changed payload. This hash is idempotency, not authorization.
Missing journal files still require explicit operator reconciliation, not automatic
enrollment. Lost/changed host IDs, rollback of authority without epoch change,
and identity spoofing by untrusted launchers remain outside this guarantee.
