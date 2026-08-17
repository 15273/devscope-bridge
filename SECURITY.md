# Security

## Model

The bridge is designed to be reachable only from the machine it runs on:

- **Loopback only.** `devscope_bridge/main.py` refuses to start unless the
  bind host is `127.0.0.1`, `::1`, or `localhost` (`_assert_loopback_host`).
  Setting `BRIDGE_HOST` to anything else is a hard error, not a warning.
- **Local token auth.** Every HTTP and WebSocket request must present the
  token from `~/.dev-bridge/token` — 32 random bytes
  (`secrets.token_hex(32)`), written with mode 0600, reused across restarts.
  Missing or wrong token → 403.
- **CORS** is restricted to the configured Chrome extension origin plus
  localhost.
- **No cloud backend.** Nothing is sent to a DevScope server — there isn't
  one. The bridge drives your locally installed `claude` / `cursor-agent`,
  and all state (token, sessions, transcripts, logs) lives under
  `~/.dev-bridge/`.

What this does *not* protect against: other processes running as your user on
the same machine. They can read the token file. That's inherent to the design
— treat the bridge as having the same trust level as your shell.

If you use the optional cockpits (WhatsApp/Gmail/Calendar/Meta Ads), OAuth
tokens also land in `~/.dev-bridge/`. Never commit that directory.

## Reporting a vulnerability

Please don't open a public issue for security bugs. Use GitHub's private
reporting on this repo: **Security → Report a vulnerability**
(https://github.com/15273/devscope-bridge/security/advisories/new).

Include steps to reproduce and what an attacker gains. It's a side project,
not a company — expect a response in days, not hours.
