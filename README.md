# OpsPilot

OpsPilot is a permission-aware operations agent. Its first workflow turns a sourcing request into a ranked supplier comparison, keeps evidence behind every recommendation, drafts quote requests and purchase orders, and requires a human decision before anything consequential can happen. The repository and some internal labels still use the earlier TaskVault name.

The interface is a neutral, evidence-first procurement workspace: ask for a product and quantity, inspect the offers, open the underlying evidence record, then create a watch or a reviewable draft. Its navigation rail, work canvas, and procurement context rail can be arranged independently. It is built with Python's standard library, SQLite, and a small browser client. There is no frontend framework or build step.

> **Demo data disclosure:** supplier records ship in `catalog/suppliers.json`. OpsPilot does not scrape live supplier sites or claim that a live page was opened. Every comparison links to a local, inspectable evidence record. Prices, stock, and lead times must be re-confirmed with the supplier before ordering.

Links pasted into a request are validated and shown as buyer-provided references. OpsPilot does not open or fetch those URLs, and they do not affect offer ranking.

## What works

- **Sourcing runs:** natural-language requests are matched to a product, quantities are normalized (pieces, boxes, cartons), and offers are ranked by landed cost, lead time, supplier rating, MOQ, and verification status.
- **Conversation recovery:** chat turns and sourcing results are stored with a conversation ID, so the current thread can be restored after a reload. The browser keeps the active ID; hosted access uses a temporary single-operator sign-in, without tenant isolation or cross-device ownership.
- **Evidence records:** each offer links to `/sources/{offer_id}`, which shows the exact listing values used in the comparison and an explicit "not a live page capture" note.
- **Isolated execution:** on macOS, research runs under a Seatbelt profile that denies network access, app database and `.env` reads, and writes to the project and user home. It gets a task-scoped temporary directory; other local paths are not comprehensively isolated. Docker remains optional where installed. Other platforms fall back to a clearly labeled process mode unless Docker is selected.
- **Human-controlled actions:** quote requests and purchase orders are drafts. Approving them records a decision; OpsPilot never sends a message, places an order, or takes a payment.
- **Price watches:** a watch compares a stored target with the latest stored evidence price. It is not a live web scraper or scheduler.
- **Voice interaction:** the microphone button supports a multi-turn browser voice conversation through the same chat and sourcing task flow. It listens again after each spoken response; recognition quality and availability depend on the browser.
- **MCP server:** nine stdio tools expose sourcing, results, watches, approvals, and the audit ledger to an MCP client.
- **Audit ledger:** task events are hash-chained. The chain is integrity-evident, not tamper-proof against an administrator who can rewrite the database.
- **Model inference:** general chat and the optional research narrative use a configured OpenAI-compatible chat-completions endpoint. The current configuration uses `VULTR_INFERENCE_*` variable names, but accepts a compatible provider endpoint. The API key stays on the backend and is never inherited by the worker.

Research works without an inference key. General chat returns `503 inference_not_configured` until an inference endpoint, model, and key are configured.

## Product direction

The contest MVP is a controlled procurement workflow, not a generic browser agent: discover offers, compare equivalent pack sizes and landed costs, show source receipts, explain trade-offs, and stop at a human approval gate. The current app computes comparisons from illustrative bundled data. It does **not** yet browse live supplier websites or expose browser screenshots, so the supplier scout in the reference brief is a target capability rather than a feature to claim today.

The strongest differentiation to build is evidence-gated execution: every extracted fact tied to a source URL and capture time, explicit freshness and uncertainty, a real isolated worker, and an auditable approval boundary. Supplier reliability should come from observed fulfillment history, not AI-generated ratings. The initial buyer, industry, and geography are open decisions to validate against each hackathon brief. The bundled catalog is illustrative USD demo data and must not be presented as live market coverage. See [PRODUCT.md](./PRODUCT.md) for product principles and [HACKATHONS.md](./HACKATHONS.md) for the event strategy, Vultr sprint, and cross-event adaptations.

## Trust boundaries

| Boundary | Behavior |
| --- | --- |
| Browser | No inference credentials. Only same-origin API calls. Rendering uses DOM text nodes rather than model-supplied HTML. |
| Web server | Holds the SQLite database and configured inference provider key. Validates public source URLs before creating a task. |
| Sourcing worker | Reads the bundled catalog and computes the comparison. No database path, inference key, or host mounts. |
| macOS Seatbelt worker | Denies network access, reads of the app data and `.env`, and writes to the project and home directories; the task directory is writable. Other local paths are not comprehensively isolated. |
| Linux Bubblewrap worker | Uses an isolated network namespace, read-only worker files, a task-only writable directory, and a minimal environment. Application data and credentials are not mounted. |
| Docker worker | Adds `--network none`, read-only root, tmpfs, memory/CPU/PID caps, `--cap-drop ALL`, and `no-new-privileges`. |
| Approvals | Store a draft and a human decision. No outbound messaging, order placement, or payment integration exists. |

The process-mode worker runs on the host and has host network and filesystem access. The current bundled-catalog worker performs no network I/O, but process mode is not a security sandbox. Receipts identify the mode and disclose the difference. Apple's `sandbox-exec` is deprecated and undocumented for third-party profile authoring; the Seatbelt mode is a local development aid, not a production isolation promise.

## Run locally

Requirements: Python 3.11+ and a modern browser. Docker is not required on this Mac; the app selects the built-in Seatbelt worker automatically. On Linux, install Bubblewrap (`bubblewrap` package) to run the sourcing worker in an isolated network namespace without Docker. The app reports a process fallback when no isolation runtime is installed; that mode is for local development only.

```bash
cp .env.example .env
python3 server.py
```

Open <http://127.0.0.1:8000>. The default listener is loopback-only.

### Configure a compatible inference provider

Set the full OpenAI-compatible chat-completions endpoint and the matching model ID. The current variable names retain their original Vultr prefix, but the endpoint can target another compatible provider:

```bash
VULTR_INFERENCE_URL=https://api.vultrinference.com/v1/chat/completions
VULTR_INFERENCE_API_KEY=...
VULTR_INFERENCE_MODEL=...
```

For local development, `TASKVAULT_COMPETITION_TRACK=development` permits any compatible endpoint. Before a Vultr Agent Rush Challenge 1 deployment, set `TASKVAULT_COMPETITION_TRACK=blast_radius_zero`; the backend then rejects agent LLM calls unless the configured HTTPS host is exactly `api.vultrinference.com`. This guard helps prevent a development fallback from accidentally reaching the submitted run. Do not use a non-Vultr provider for agent calls in the Challenge 1 submission.

Do not put the key in `app.js`, the catalog, the worker, or the browser. Restart the server after changing environment variables. `/api/health` reports whether inference is configured; **Connections → Test model connection** sends one short request to confirm the endpoint responds (provider usage may apply).

### Local macOS sandbox mode

```bash
TASKVAULT_SANDBOX_MODE=seatbelt python3 server.py
```

`TASKVAULT_SANDBOX_MODE=auto` (the default) selects macOS Seatbelt on this Mac and Bubblewrap on Linux when available, then Docker, then process fallback. You can choose `bubblewrap` or `process` explicitly. Explicit isolation modes fail closed if their runtime is missing. Receipts report the mode that actually ran. The Connections containment check probes an external address to confirm that the active sandbox blocks network access.

## Hosted deployment

The current Contabo deployment serves the frontend and API from one same-origin app behind Nginx, with HTTPS, a single-operator sign-in, and rate limiting. See [DEPLOYMENT.md](./DEPLOYMENT.md) for the server layout and security limits. Do not expose a local instance directly to the internet.

The Linux process fallback is not a secure worker boundary. Use Bubblewrap or Docker for isolated sourcing. The Contabo site uses a branded single-operator sign-in with an in-memory session; it is suitable for one private operator, not multiple organizations.

### Containment check

```bash
curl -s http://127.0.0.1:8000/api/sandbox/test \
  -H 'Content-Type: application/json' \
  -d '{"confirm":true}'
```

The receipt lists the mode, network policy, filesystem policy, limits, exit code, and teardown. The result confirms that the worker did not inherit a database path, an inference key, or secret-named environment variables.

## Demo path

1. Ask: `Source 500 boxes of nitrile examination gloves.`
2. Inspect the ranked offers and open an evidence record.
3. Create a price watch at a target price and check it.
4. Draft a quote request, then a purchase order, and review it in Approvals.
5. Approve or reject the draft. No external action is taken.
6. Run **Connections → Run containment test**.
7. Open **Activity** to inspect the hash-chained event ledger.
8. Use the microphone button in Chrome on localhost or HTTPS for the voice session.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Catalog metadata, inference readiness, sandbox mode. |
| `POST` | `/api/inference/check` | Send a short server-side request to verify the configured model endpoint. |
| `POST` | `/api/chat` | Research requests return `202` with a task ID; general chat returns a model answer. |
| `GET` | `/api/tasks` | Recent tasks. |
| `GET` | `/api/tasks/{id}` | Task, result, research payload, and sandbox receipt. |
| `GET` | `/api/tasks/{id}/result` | Stored result payload. |
| `GET` | `/api/tasks/{id}/events` | Task audit events. |
| `GET` | `/api/conversations/{id}` | Restore a saved conversation and its completed sourcing results. |
| `POST` | `/api/tasks/{id}/stop` | Request a stop before or between sandbox steps. |
| `GET` | `/sources/{offer_id}` | Inspect the exact evidence record behind an offer. |
| `POST` | `/api/voice/ask` | Legacy evidence-only voice answer; the current voice UI uses `/api/chat` to share task and conversation context. |
| `GET`/`POST` | `/api/watches` | List or create a price watch. |
| `POST` | `/api/watches/{id}/check` | Check a watch against stored evidence. |
| `GET`/`POST` | `/api/approvals` | List or create a reviewable draft. |
| `POST` | `/api/approvals/{id}/decision` | Record an approve/reject decision. |
| `GET`/`POST` | `/api/profile` | Buyer profile and approval threshold. |
| `POST` | `/api/sandbox/test` | Run the containment self-test. |
| `GET` | `/api/activity` | Audit events and chain validity. |

Research requests are asynchronous: the server creates the task, starts a background worker, and returns `202`. The client polls `/api/tasks/{id}` until the task settles.

## MCP tools

`.vscode/mcp.json` starts `mcp_server.py` over stdio.

- `create_research_task`
- `source_suppliers`
- `list_research_tasks`
- `get_research_result`
- `create_price_watch`
- `list_price_watches`
- `list_approvals`
- `decide_approval`
- `get_audit_activity`

`source_suppliers` runs the same bounded worker and stores a completed task with evidence. It does not browse the live web or perform external actions.

## Data and catalog

- Database: `data/taskvault.sqlite3` (configurable via `TASKVAULT_DB_PATH`).
- Catalog: `catalog/suppliers.json`, version `2026.11.05`, 7 products and 21 offers.
- Product artwork: `assets/products/*.svg`; mascot: `assets/taskvault-mascot.png`.
- The catalog is demonstration data. Prices are USD and include the modeled shipping/free-shipping rules shown in each evidence record.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite covers task storage and the audit chain, URL validation, inference configuration, research and quantity normalization, drafts, process/macOS Seatbelt/Docker sandbox receipts, MCP tools, the full research/watch/approval/profile HTTP flow, evidence pages, and containment.

## Current limitations

- The supplier index is bundled; there is no live supplier crawling or browser worker.
- Buyer-provided URLs are displayed as references only; they are not fetched or used to rank offers.
- Price watches are manual checks against stored evidence; there is no scheduler or push notification.
- Voice recognition and synthesis are browser features. They may use the browser vendor's recognition service. Voice is a conversational interface to OpsPilot's existing workflow, not a supplier phone call.
- Approvals record a human decision. Outbound email, supplier calls, checkout, and order placement are intentionally not implemented.
- Local development has authentication disabled by default. The hosted deployment enables a single-operator sign-in gate; it does not provide multi-user authentication or tenant isolation.
- The audit chain is not tamper-proof against an administrator who can rewrite the database and recompute hashes.

## Prior art

The permission and approval model was informed by a review of OpenMausBot (Apache-2.0; its `enterprise/` directory is separately licensed and was not used) and openclaw-voice-call-realtime (MIT). No third-party source code is vendored in this repository; the voice flow uses the browser Web Speech API rather than Twilio or OpenAI Realtime.
