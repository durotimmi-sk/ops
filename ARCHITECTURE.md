# TaskVault Architecture

TaskVault is a permission-aware autonomous operations agent designed for evidence-backed supplier sourcing and procurement intelligence.

## System Components

```
+-------------------------------------------------------------------+
|                        Client Layer                               |
|   - Web Interface (ChatGPT-class Workspace + Gold Accents)       |
|   - MCP Server (mcp_server.py) for Claude / external AI IDEs      |
|   - Push-to-Talk Browser Voice Channel                            |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|                     Control Plane (server.py)                     |
|   - Task Lifecycle & Queue Management                             |
|   - REST API (/api/v1/tasks, /evidence, /approvals, /watches)     |
|   - SSE Event Streaming (/api/v1/tasks/{id}/events?stream=true)   |
|   - Vultr Serverless Inference Client (api.vultrinference.com)   |
|   - Hash-Chained Audit Ledger Engine                              |
+-------------------------------------------------------------------+
                  |                                 |
                  v                                 v
+-----------------------------------+   +---------------------------+
|    Persistence (taskvault_core)   |   |   Procurement Engine      |
|   - SQLite (Production SQLite3)   |   |   (taskvault_research.py) |
|   - tasks, task_steps, events     |   |   - Offer comparison      |
|   - task_captures (Screenshots)   |   |   - Landed-cost scoring   |
|   - approvals, price_watches      |   |   - Dynamic product parse |
+-----------------------------------+   +---------------------------+
                  |
                  v
+-------------------------------------------------------------------+
|            Execution Sandbox (taskvault_sandbox.py)               |
|   - Isolation: Linux Bubblewrap / macOS Seatbelt / Docker         |
|   - Zero secret inheritance; non-root user execution              |
+-------------------------------------------------------------------+
                  |
                  v
+-------------------------------------------------------------------+
|            Browser Worker (browser_worker.py)                     |
|   - Headless Chromium (Playwright)                                |
|   - Read-only capture: text excerpt + timestamped screenshot      |
|   - SHA-256 evidence digests                                      |
+-------------------------------------------------------------------+
                  |
                  v
+-------------------------------------------------------------------+
|          Egress Allowlist Proxy (taskvault_egress.py)             |
|   - HTTPS 443 CONNECT tunnel only                                 |
|   - Domain name allowlist matching                                |
|   - Anti-SSRF: Private, local, and metadata IP deny rules         |
+-------------------------------------------------------------------+
```

## Data Flow: Evidence-Gated Procurement

1. **Intake**: Buyer inputs a sourcing requirement (e.g. `Source 500 boxes of nitrile gloves`) with optional public supplier links.
2. **Clarification**: If key parameters (such as quantity or unit) are missing, TaskVault requests structured clarification before executing.
3. **Sandbox Launch**: The control plane spins up a disposable worker with a scoped temporary workspace and no credentials.
4. **Read-Only Browser Capture**:
   - The worker routes all browser network requests through `taskvault_egress`.
   - Disallowed protocols (`file://`, `ws://`) and non-allowlisted domains are blocked and recorded.
   - For valid destinations, visible DOM text and viewport screenshots are captured and hashed (`SHA-256`).
5. **Deterministic Extraction & Normalization**:
   - Unit prices, minimum order quantities (MOQ), and shipping lead times are extracted from captures.
   - Landed cost is calculated deterministically (`unit_price * max(qty, moq) + shipping`).
   - If values cannot be parsed from the page, they remain `unknown`—never hallucinated.
6. **Vultr Serverless Inference Integration**:
   - High-level procurement narratives and summaries are generated via Vultr Serverless Inference (`api.vultrinference.com`).
   - All factual claims cite the captured evidence record and screenshot link.
7. **Action Gating**:
   - Any follow-up action (drafting a purchase order or sending a quote inquiry) enters an approval state.
   - Actions are paused until human operator sign-off.
