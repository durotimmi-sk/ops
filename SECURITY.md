# TaskVault Security & Containment Architecture

## Overview
TaskVault is built for **Blast Radius Zero**: an autonomous operations and supplier intelligence agent designed so that even if the agent encounters hostile web pages, prompt injections, or malicious redirects, it cannot access internal network assets, leak infrastructure credentials, or execute unapproved actions.

---

## 1. Trust Boundaries

```
[ Buyer / Operator ]
        |
        v  HTTPS (Session Auth / Read-only UI)
[ TaskVault Control Plane ] (FastAPI / Server)
   - Holds Vultr Serverless Inference credentials
   - Manages SQLite/Postgres task state & hash-chained audit ledger
   - Enforces human-approval gates for external actions
        |
        v  Isolated Worker Launch (bwrap / seatbelt / docker)
[ Disposable Browser Worker ] (Playwright)
   - Non-root user (UID 10001)
   - Read-only filesystem
   - NO API keys, NO database access, NO environment secrets
        |
        v  Loopback HTTP CONNECT Proxy
[ Egress Allowlist Proxy ] (taskvault_egress)
   - Resolves DNS independently
   - Rejects RFC 1918, link-local, loopback, cloud metadata (169.254.169.254)
   - Aborts non-HTTPS protocols (file://, ws://, ftp://, data:)
   - Only allows explicitly authorized public domain names
```

---

## 2. Containment Principles

### Non-Root Execution
- Workers run under an unprivileged user ID (10001) with dropped capabilities and `no-new-privileges`.
- Temporary task storage is mounted as a scoped `tmpfs` and destroyed on worker exit.

### Zero Secret Inheritance
- The worker process environment is sanitized: `VULTR_INFERENCE_API_KEY`, database credentials, and operator sessions are never passed to the worker.
- Probed and verified by the `/api/sandbox/test` self-test endpoint.

### Strict Egress & Anti-SSRF Defense
- The browser process cannot make arbitrary outbound requests.
- All requests route through a local allowlist proxy (`taskvault_egress.py`).
- Target hostnames are normalized and matched strictly against the task's allowlist.
- IP addresses are checked against private and reserved CIDR ranges:
  - `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `127.0.0.0/8`
  - `169.254.0.0/16` (including cloud metadata `169.254.169.254`)
  - `172.16.0.0/12`, `192.168.0.0/16`, `224.0.0.0/4`, `240.0.0.0/4`
- Redirects are intercepted and re-validated at runtime so malicious pages cannot pivot to blocked internal services.

### Read-Only Browser Execution
- The browser worker is strictly read-only: it visits allowed URLs, waits for DOM content, extracts visible text excerpts, and saves timestamped screenshots.
- It never submits forms, executes model-generated scripts, clicks unapproved elements, or downloads executable files.

### Kill Switch & Bounded Lifecycle
- Every run is bounded by wall-clock timeout (75 s total, 15 s per page), CPU limit (60 s), and file size limits (32 MB).
- Immediate stop endpoint (`POST /api/tasks/{id}/stop`) terminates the worker and destroys temporary profiles.

---

## 3. Human-in-the-Loop Approval Gates
- Generating a quote request or purchase order creates a draft approval record (`quote_request` or `purchase_order`).
- No email, message, payment, or outbound contract is ever sent autonomously.
- Actions require explicit human operator approval with digital signature in the audit chain.

---

## 4. Hash-Chained Audit Ledger
- All task state transitions, browser capture events, and approval decisions are appended to an audit ledger (`task_events`).
- Each event is cryptographically linked to the previous event via SHA-256 hash chaining, enabling instant tampering detection.
