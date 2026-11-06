# OpsPilot (TaskVault)

OpsPilot is a permission-aware, sandboxed autonomous operations agent for supplier sourcing and procurement intelligence. Built for **Vultr: Agent Rush Hackathon (Challenge 01: Blast Radius Zero)**, OpsPilot turns a natural-language sourcing request into a verified supplier comparison, captures timestamped browser evidence inside an isolated worker, calculates deterministic landed costs, and enforces a strict human-approval gate before any consequential purchase order or inquiry can proceed.

---

## ⚡ Built on Vultr (Hackathon Architecture)

OpsPilot uses Vultr infrastructure as the centralized system of control, orchestration, and inference:

1. **Vultr Cloud Compute (Backend Control Plane)**:
   - Hosts the FastAPI/HTTP orchestration server, task lifecycle state, and SQLite database.
   - Manages asynchronous task queues, SSE event streaming, and the hash-chained audit ledger.
2. **Vultr Serverless Inference (`api.vultrinference.com`)**:
   - All agent LLM calls route through Vultr Serverless Inference via OpenAI-compatible endpoints.
   - Enforced by `TASKVAULT_COMPETITION_TRACK=blast_radius_zero`, which blocks any non-Vultr inference provider at the transport layer.
   - Used for narrative extraction, trade-off summarization, and claim verification while keeping API credentials strictly isolated from execution workers.
3. **Isolated Sandbox Execution (Blast Radius Zero)**:
   - Worker tasks execute in disposable, non-root containers (Docker / Bubblewrap).
   - **Zero Secret Inheritance**: Workers have no database path, no Vultr API keys, and no host volume mounts.
   - **Egress Containment**: Outbound traffic routes through a local allowlist proxy (`taskvault_egress.py`) that aborts non-HTTPS traffic, revalidates DNS, and blocks private networks, loopback, and cloud metadata (`169.254.169.254`).

---

## What Works

- **Read-Only Browser Worker**: When public supplier links are provided, a disposable Playwright browser worker visits target pages, extracts visible product details, and captures full-resolution PNG screenshots saved with SHA-256 evidence digests.
- **Evidence-Gated Procurement**: Every extracted fact (unit price, MOQ, delivery timeline) is paired with a timestamped screenshot and source URL. Missing fields remain explicit unknowns—never fabricated.
- **Live Landed-Cost Comparison**: Computes order units, package conversions (pieces $\rightarrow$ boxes $\rightarrow$ cartons), delivery shipping rules, and landed unit costs across offers.
- **Dynamic Product Sourcing**: Accepts any product request (e.g. *KN95 respirators*, *nitrile gloves*, *surgical drapes*), extracting product attributes dynamically.
- **Guided Clarification**: If a quantity or unit is omitted, the agent prompts for structured clarification before execution.
- **Human Approval Gate**: Quote inquiries and purchase order drafts require explicit operator approval; OpsPilot never autonomously executes orders, sends external emails, or initiates payments.
- **Real-Time SSE Event Streaming**: Live worker navigation, capture status, and verification steps stream in real time via Server-Sent Events (`/api/v1/tasks/{id}/events?stream=true`).
- **Hash-Chained Audit Ledger**: Every task transition, capture receipt, and approval decision is cryptographically chained (`SHA-256`) for tamper-evident activity auditing.
- **MCP Server**: 9 standard tools exposed via `mcp_server.py` for external IDE and agent integrations.
- **Browser Voice Channel**: Multi-turn voice interaction powered by browser Web Speech APIs.

---

## Trust Boundaries & Containment

| Boundary | Behavior |
| --- | --- |
| **Browser Client** | No inference credentials. Only same-origin API calls. Renders sanitized DOM text nodes rather than arbitrary model HTML. |
| **Control Plane** | Runs on Vultr VM. Holds SQLite database and Vultr Inference key. Validates URLs before dispatching tasks. |
| **Browser Worker** | Disposable Playwright container. Non-root user (UID 10001), read-only root, temporary scoped `tmpfs`, CPU/memory limits. |
| **Egress Proxy** | Accepts HTTPS CONNECT tunnels for allowlisted domains only. Re-resolves DNS and rejects private/link-local/metadata IPs (`169.254.169.254`). |
| **Approvals** | Consequential actions (quotes, POs) generate pending drafts requiring human signature. No external execution API exists. |

---

## Quickstart & Deployment

### Run with Docker Compose (Recommended)

```bash
# 1. Clone repository
git clone https://github.com/durotimmi-sk/ops.git
cd ops

# 2. Configure environment
cp .env.example .env
# Edit .env with your Vultr credentials:
# VULTR_INFERENCE_URL=https://api.vultrinference.com/v1/chat/completions
# VULTR_INFERENCE_API_KEY=your_vultr_key
# VULTR_INFERENCE_MODEL=your_model

# 3. Start services
docker compose up -d --build
```
Open <http://127.0.0.1:8000> in your browser.

### Run Locally (Python)

```bash
python3 server.py
```

### Containment Self-Test

Verify that workers cannot inherit credentials or access prohibited network ranges:
```bash
curl -X POST http://127.0.0.1:8000/api/sandbox/test \
  -H "Content-Type: application/json" \
  -d '{"confirm": true}'
```

---

## API Reference

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | System status, Vultr inference check, sandbox mode. |
| `POST` | `/api/v1/tasks` | Create and queue a sourcing task. |
| `GET` | `/api/v1/tasks/{id}` | Get task status, result, and execution receipt. |
| `GET` | `/api/v1/tasks/{id}/events` | Stream task events via SSE (`?stream=true`). |
| `GET` | `/api/v1/tasks/{id}/evidence` | List all screenshot evidence and extracted claims. |
| `GET` | `/api/v1/tasks/{id}/captures` | List raw page captures and metadata. |
| `POST` | `/api/v1/tasks/{id}/stop` | Emergency kill switch to terminate worker. |
| `GET`/`POST` | `/api/approvals` | List drafts or record human approval decisions. |
| `POST` | `/api/sandbox/test` | Run containment verification probe. |

---

## Test Suite

```bash
python3 -m unittest discover -s tests -v
```
Runs 34 automated unit and integration tests covering:
- Egress allowlist proxy and SSRF defense
- Read-only browser capture worker and screenshot hashing
- Deterministic landed-cost normalization and dynamic product resolution
- Task lifecycle, SSE event streaming, and `/api/v1` routes
- Containment self-tests and zero-secret inheritance
- Hash-chained audit ledger integrity
- MCP tools and voice inquiry routing

## Prior art

The permission and approval model was informed by a review of OpenMausBot (Apache-2.0; its `enterprise/` directory is separately licensed and was not used) and openclaw-voice-call-realtime (MIT). No third-party source code is vendored in this repository; the voice flow uses the browser Web Speech API rather than Twilio or OpenAI Realtime.
