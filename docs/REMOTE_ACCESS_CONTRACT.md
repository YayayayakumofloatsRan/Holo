# Holo Remote Access Contract

Holo mobile access has three transport levels:

- USB debug: `adb reverse tcp:8004 tcp:8004`, mobile URL `http://127.0.0.1:8004`.
- Private network or overlay: a stable device address, such as a Tailscale
  address, forwarded to the same local Holo API.
- Public tunnel: an HTTPS tunnel such as Cloudflare Tunnel pointing at
  `http://127.0.0.1:8004`.

## Authentication Boundary

Any transport beyond local USB should set `HOLO_API_BEARER_TOKEN` before
starting Holo:

```powershell
$env:HOLO_API_BEARER_TOKEN = "<long random token>"
D:\Holo\holo\scripts\holo-wsl-start-all.ps1
```

When the token is set, every Holo HTTP endpoint requires:

```text
Authorization: Bearer <long random token>
```

The mobile Holo connection sheet stores the same bearer token and sends it on
`/health` and `/reply`. Mobile still has no memory-reset authority; memory reset
remains WSL CLI-only.

## Cloudflare Quick Tunnel

For a quick cross-network test:

```powershell
$env:HOLO_API_BEARER_TOKEN = "<long random token>"
D:\Holo\holo\scripts\holo-cloudflare-quick-tunnel.ps1
```

Use the printed `https://*.trycloudflare.com` URL in the mobile Holo connection
settings and save the same bearer token. Quick Tunnel URLs are temporary; use a
named Cloudflare Tunnel for a stable domain.

## Private Overlay

For long-running private access, use an overlay network such as Tailscale and
point the mobile app at the overlay HTTPS/HTTP endpoint. Keep the bearer token
enabled even inside a private overlay, because the Holo API exposes diagnostics
and operational endpoints in addition to `/reply`.
