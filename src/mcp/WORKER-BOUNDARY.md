# Experimental worker filesystem boundary

This is an isolated, model-free proof of a worker/service boundary, not a
production deployment, MCP replacement, or complete G3 gate pass. Existing
`stdio.ts` and direct database adapters are unchanged and do **not** acquire
isolation merely because these scripts exist.

The trusted operator runs `worker_service.py DATABASE PROJECT SOCKET` outside
an unprivileged bubblewrap namespace. The operator must select a disposable or
otherwise authorized authority database. The server refuses an existing socket
path and exposes only `wiki_page`, `wiki_read`, `wiki_propose`, `wiki_operation`.
Identity and project are fixed at launch to the worker role, never request data.
Requests are newline JSON objects containing exactly `tool` and `args`.
Mutation requests require an explicit idempotency key. No curator, publication,
index-management, arbitrary path, URL fetch, or hybrid-recall operation is exposed.
Errors omit underlying private details. Request size and I/O deadlines are bounded.
This serial test server is not a throughput or availability guarantee.

`sandbox_worker.py SOCKET -- COMMAND ...` exposes `/run/wiki.sock` and read-only
system runtime to a command. It clears the inherited environment, creates private
PID/proc/network/IPC/UTS namespaces, and provides empty temporary/home directories.
It neither mounts host HOME nor the authority database/curator files. It has no
unsandboxed fallback. The worker cannot use external model APIs: network isolation
is deliberate for this test profile.

The socket is a worker capability. Anyone who can use that socket can perform
its allowed worker operations. Multiple callers share the worker principal.
The service and sandbox launcher still run under the operator's UID. Other
**unsandboxed** processes with that UID, host administrators, and kernel exploits
are outside this boundary. No new account, system service, firewall, global
permission, or persistent authentication change is made.

Validation uses synthetic SQLite data and secrets only:

```text
/tmp/hypothesis-env/bin/python -m pytest tests/hypothesis/test_worker_boundary.py -q
```

Tests execute real API reads/proposals with persisted idempotent receipts, forged
identity/project/database/tool denials, denied file opens including `/proc/1/root`,
environment scrubbing, distinct network namespace, and malformed-request survival.
They do not establish a complete host rollout, hybrid retrieval, independent
curator OS identity, durable host-call journal, production load, or adversarial
model behavior. Those remain separate acceptance gates.
