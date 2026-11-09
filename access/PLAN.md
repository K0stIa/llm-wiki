# LAN agent interfaces

Approved scope: reuse Raspberry Caddy; protected LAN-only routes; separate SSH forwards; preserve HA and existing Pi/OpenCode sessions; no public route, credential disclosure, OS trust installation, or existing tunnel restart.

- Record baseline HA and app health.
- Generate private local login; prepare remote backup/candidate without activating.
- Start two SSH Unix-socket forwards, then verify upstreams.
- Validate Caddy 2.6.4 candidate and negative source/auth rules.
- Reload once, verify LAN auth, HTTPS, Pi WebSocket, denied bridge source, HA reconnect, and session survival.
- Preserve rollback copy and give local credential/certificate instructions.

Caddy 2.6.4 reload may close existing WebSockets. Do not add unsupported stream-close-delay options or upgrade Caddy.
