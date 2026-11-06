# Deployment plan

## Contabo host layout

Run the frontend and backend on the existing Contabo Ubuntu server as one same-origin app. Nginx serves `opspilot.pontly.africa` over HTTPS and proxies to the Python app on `127.0.0.1:8120`. The OpsPilot service uses its own Linux account, systemd unit, SQLite database at `/var/lib/opspilot/opspilot.sqlite3`, and environment file under `/etc/opspilot/`. Existing Nginx sites, services, and PostgreSQL databases remain separate.

Keeping the UI and API on one origin avoids Vercel build configuration and cross-origin API setup. Vercel remains an option if global static delivery becomes important; it is not needed for the first server deployment.

## Access and production limits

The hosted site uses a branded, single-operator sign-in overlay over HTTPS. The server verifies a PBKDF2-SHA256 password hash and issues a 12-hour HttpOnly, SameSite=Strict session cookie marked Secure behind HTTPS. Sessions are held in memory and expire when the service restarts. This is a temporary access gate, not a multi-user identity system: do not share this login with buyers or onboard other organizations until native accounts, authorization, and tenant-scoped records exist. Generate or change the password hash with `python3 deploy/contabo/hash_password.py`; keep the resulting hash in `/etc/opspilot/opspilot.env` and never commit it.

The server database is a dedicated SQLite file. It is isolated from the existing projects' databases and is appropriate for this single-operator pilot. Add scheduled backups and a restore check before storing real purchasing records. Inference credentials belong only in `/etc/opspilot/opspilot.env`, which is root-owned and mode `0600`; they are not currently configured.

## Worker boundary

The Contabo service uses Bubblewrap on Linux; Docker is not required. Ubuntu's AppArmor policy restricts unprivileged user namespaces by default, so deployment adds a small profile for the Bubblewrap executable without changing that system-wide policy. The worker receives only its code, the bundled sample catalog, and a task-scoped temporary directory. It runs in a separate network namespace, with a minimal environment and resource/time limits. The Connections containment check must pass on the actual host before exposing the app. The bundled worker still does not browse supplier websites; live supplier research remains disabled until an egress allowlist, real evidence capture, and source verification are implemented.

## Current rollout

1. Install the app in `/opt/opspilot` and run it as the `opspilot` system user, bound to loopback on port `8120`.
2. Provision Bubblewrap, a separate persistent database directory, Nginx rate limits, and the single-operator sign-in gate.
3. Issue an origin TLS certificate for `opspilot.pontly.africa` so Cloudflare can establish HTTPS to Nginx.
4. Confirm the service is healthy, check that the sandbox containment probe passes, then verify the protected public site and its API.
5. Add model credentials only after the owner supplies them; add scheduled backups before using real records.
6. Implement native authentication and tenant isolation before enabling multiple users. Build a domain-allowlisted live research worker before collecting supplier data from the web.

## Local bundle

The complete app is served from the Python process on the server. Keep the Vercel build files for future use, but do not deploy `dist/` for this same-origin layout. Never include `.env`, `data/`, local browser profiles, or SSH credentials in a release archive.
