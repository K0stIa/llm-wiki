# Verified LAN setup, 2026-11-09

OpenCode: https://192.168.0.168/
Pi: https://192.168.0.168/pi/

Passed: unauthenticated pages/API/WebSocket 401; authenticated OpenCode health, HTML, JS/CSS, SSE; Pi prefixed page/token/WebSocket with live screen; foreign-origin WebSocket rejected; Pi PID 3007229 unchanged after viewer disconnect.

Isolation: actual cloudflared-container HTTP origin with IP Host returned 404; HTTPS request from 172.19.0.1 with valid credentials and forged forwarding headers returned 404. Existing Cloudflare ingress and router/firewall settings were not changed. No independent off-site client/router audit was performed.

HA regression: existing HTTP route 200; WebSocket reconnect 101 and auth_required. No HA authentication or device-control actions. Caddy, HA, cloudflared container start times unchanged. Caddy configuration was reloaded twice; second reload fixed no-SNI IP certificate selection on Caddy 2.6.4.

TLS: scoped verification uses the existing public Caddy CA certificate, with an IP-SAN leaf for 192.168.0.168. No client or host OS trust installation performed. Caddy initially auto-installed its CA inside its own container; skip_install_trust now prevents further automatic installation. No browser security warning was bypassed.

Remote config: /opt/caddy/Caddyfile. Original rollback copy: /opt/caddy/agent-ui-relay/Caddyfile.before. Task versions and active SHA256 are in that private directory. Do not restore over later unrelated edits; compare current SHA256 against active.sha256 first.

Credentials remain only in private local login.json and as bcrypt hash in the private Caddy configuration. No credential values in reports or logs. No model prompts or Pi keyboard input sent. Browser visual rendering and client trust setup remain unverified.
