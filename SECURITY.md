# Security

Please report a vulnerability privately, through this repository's **Security** tab, **Report a
vulnerability**. Do not open a public issue for it.

This is a project kept by volunteers, with no promised response time and no supported versions:
fixes land on the default branch.

## Running it safely

- The api, the web and the worker are built for a machine or a network you trust. They have no TLS
  of their own, and `docker compose` publishes ports 3000 and 5173 on every network interface. Use a
  firewall, and put a reverse proxy with TLS in front before exposing them to anyone else.
- The browser profiles in `storage/sessions/` are logged-in accounts. Whoever reads them is signed
  in as you. Keep `storage/` and `.env` private, and keep them out of backups you share.
- Replace all three `change-me` values in `.env` with long random strings, and keep `INVITE_CODE` to
  the people you mean to let in. The first account registered on an empty database is the admin.
- Worker `/health` listens on localhost and tells which accounts are served. Do not publish its port.
