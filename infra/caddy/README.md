# infra/caddy

Isolated Caddy config snippets for Legal ARAG.

## Non-destructive rollout for external Caddy

1. Keep existing virtual hosts unchanged.
2. Copy `Caddyfile.legal.build` to your include directory (for example `/etc/caddy/sites-enabled/legal.build.caddy`).
3. In the main Caddyfile, include site snippets:

```caddy
import /etc/caddy/sites-enabled/*.caddy
```

4. Validate and reload:

```bash
caddy validate --config /etc/caddy/Caddyfile
caddy reload --config /etc/caddy/Caddyfile
```

## DNS prerequisites

- The only valid public deployment host for this project is `legal.build`.
- `legal.build` must resolve to the Caddy host (`A`/`AAAA` records).
- Automatic TLS requires reachable ports `80` and `443`.

## Tracking

Access logs are written in JSON to:

`./logs/legal.build.access.log` (relative to Caddy working directory)
