# Hackathon strategy

## Product thesis

**OpsPilot is a permission-aware operations agent that completes bounded browser work and returns evidence a person can inspect.** The initial product workflow is supplier research and quote comparison because it is already represented in this codebase. That is a starting workflow, not a claim that OpsPilot is specific to Lagos, Nigeria, or any one market. Buyer, sector, location, currency, and data sources must be chosen from each event's brief and validated with users.

The product should stand out through its execution contract, not by adding the largest number of integrations:

1. The operator describes a goal and constraints, by typing or speaking.
2. OpsPilot asks about missing information instead of silently guessing.
3. A deterministic policy layer turns the request into a bounded, read-only task plan.
4. A disposable worker performs the browser work; it has no app credentials, database, or unrestricted host access.
5. Each factual result is returned with the URL, screenshot, capture time, extracted value, and verification state.
6. The app marks missing, conflicting, stale, and unverified facts explicitly and explains the ranking logic.
7. It prepares a draft for a person to review. It cannot send, buy, pay, or submit a consequential form without a separate permission and confirmation.
8. The task can be stopped, resumed, or retried, with the events and worker teardown visible.

That gives the demo a strong answer to “what did the agent do, what evidence supports it, and what did containment prevent?” A swarm is useful only when roles create measurable checks. Start with one orchestrator and bounded roles (planner, browser worker, verifier); parallelize independent source reads only after the single-worker lifecycle is reliable. Do not create five unconstrained LLM personas.

## Event portfolio

| Priority | Event | Fit | Adaptation | Decision |
|---|---|---|---|---|
| 1 | [Vultr Agent Rush](https://community.vultr.com/e/vultr-agent-rush-hackathon) | Very strong | Ship the browser execution loop inside a disposable Vultr sandbox and use Vultr Serverless Inference for every agent LLM call in Challenge 1. Make containment a first-class part of the demo. | Immediate sprint; deadline Nov 8, 2026. |
| 2 | [BCH BLAZE 2026](https://bchblaze.com/) | Conditional | Only enter if we can add a real Bitcoin Cash use case: e.g. a supplier-quote workflow that creates a buyer-approved, inspectable BCH payment request or escrow/settlement action using the required BCH ecosystem integration. No speculative payments and no blockchain decoration. | Register by Nov 13; decide after reviewing official DoraHacks track and bounty requirements. Build period Nov 14–22. |
| 3 | [Atlassian Codegeist 2026](https://codegeist2026.devpost.com/) | Strong later fit | Build a separate Forge app for Jira/Confluence procurement intake: a request becomes an evidence-backed sourcing task, with status and approval returned to the relevant issue. For an agent/MCP prize, expose narrowly scoped Forge tools through Atlassian's required Rovo MCP module. | Good follow-on; deadline Dec 22, 2026. Keep OpsPilot as the service and build a contest-specific Forge integration, not a wholesale rewrite. |

These are related product surfaces, not one submission with every integration bolted on. Each event has its own required platform and judging story. Verify eligibility, rules, sponsor integrations, and final timestamps on the organizer's current page before submitting.

## Priority 1: Vultr Agent Rush

### Challenge choice

Target **Challenge 1: Blast Radius Zero**, specifically sandboxed browser use. The challenge requires a web application, a Vultr VM control plane, isolated execution on Vultr, and Vultr Serverless Inference for agent LLM calls. Challenge 2 (Powering the Future of Work) includes procurement as a domain and does not require Serverless Inference, but Challenge 1 is the better fit for the existing research/evidence workflow and the user's stated sandbox direction. Do not claim Challenge 1 compliance until the app and worker are actually deployed on Vultr and the worker boundary is demonstrated.

### Demo concept: OpsPilot Evidence-Gated Sourcing

Use a geography-neutral request such as “Find three suppliers for this item and quantity, compare the offers, and prepare a recommendation.” The operator chooses the destination or the UI uses a synthetic destination clearly labelled as test data. The run browses a small set of public supplier pages, captures screenshots, normalizes equivalent units, labels unknowns, and produces a recommendation with evidence. Finish with a draft quote request held behind an approval card.

The memorable moment is a harmless malicious page or a deterministic containment probe: it asks the worker to read a fake secret or access a forbidden local/metadata address. Show that the worker has no secret to reveal, that the request is blocked, that the run records the denial, and that the worker is destroyed. Do not execute destructive commands on the host or use real credentials in the demo.

### Required submission checklist

- Public GitHub repository with reproducible setup, architecture, security boundaries, limitations, and license/attribution notes.
- Backend deployed on a Vultr VM; agent LLM calls routed through Vultr Serverless Inference.
- Disposable browser worker on Vultr with per-run limits and teardown; no inference key, database file, cloud credentials, Docker socket, or host mounts exposed to it.
- Public demo URL with a real task run and a product-quality UI.
- Short recorded video showing normal execution and one containment moment.
- Clear, accurate use-case and architecture explanation, plus official LabLab submission.
- Verify remote submission and attendance eligibility in the event rules; the Salt Lake City showcase is an optional/approved in-person phase, and travel is not funded.

The current workspace inventory does not show a root `LICENSE` file. The event page says submissions must be original and MIT-compliant, so resolve the project licensing and third-party notices before making the contest repository public; do not assume that merely referencing open-source projects makes the submission compliant.

### What can be claimed today

The current OpsPilot/TaskVault codebase is a working procurement UI and backend with task persistence, comparison logic, audit records, approval drafts, and local containment modes. The bundled suppliers are illustrative. It does not currently perform live supplier browsing with screenshot receipts, and the public site is on Contabo. For the event, keep Contabo serving its current app and create a separate Vultr deployment for the contest rather than moving or disturbing the other project. The current local sandbox implementation is useful groundwork, but the Vultr worker must be proven independently against the event requirements.

### Build order for the remaining event window

1. **Eligibility and credits:** register on LabLab and the event Discord, confirm online judging/submission rules, obtain the official participant gift code, and verify the $200 credit balance before provisioning resources.
2. **Smallest Vultr deployment:** deploy the existing backend/UI on a low-cost Vultr VM; wire Vultr Serverless Inference in the backend; confirm a real model call. Set budget alerts and shut down unneeded resources.
3. **Containment before browsing:** create a disposable worker with strict CPU, memory, PID, wall-clock, storage, and network limits; block private, loopback, link-local, and metadata destinations, including after DNS/redirect resolution; keep all credentials outside the worker; capture lifecycle events and destroy it after each run.
4. **One successful real browser task:** support a tight, read-only allowlist or small source set; save screenshot and URL receipts; extract a small fixed schema; show unknown/conflicting values rather than inventing them.
5. **Verification and human boundary:** compare units consistently, make the scoring formula inspectable, mark freshness, and ensure the quote/action output remains a draft. Add a stop control and show cancellation/teardown.
6. **Polish the contest surface:** keep the existing OpsPilot visual language, improve hierarchy and execution progress, make evidence open in one click, expose exact sandbox status, and make the demo accessible without production credentials.
7. **Submission and rehearsal:** write setup/architecture/security docs, run repeatable happy-path and hostile-page scenarios, record the video, rehearse from a clean browser, and submit before the organizer's cutoff (verify the timezone in LabLab; a listing currently reports Nov 8 at 11 PM UTC).

If any required isolation or live evidence step is unreliable, narrow the tested source set and demonstrate that exact boundary honestly. Do not substitute a fabricated “successful” browser run for missing functionality.

## Reuse decisions

### OpenMausBot

[OpenMausBot](https://github.com/milind-soni/OpenMausBot) is Apache-2.0 at the repository level, while its `enterprise/` directory has separate licensing. It is a substantial desktop/harness product with agents, a normalized event stream, approvals, MCP, voice, and computer use. Reuse the product patterns and inspect individual dependencies before copying code. Do not fork its Electron shell, local CLI runtime, or complete harness into OpsPilot: those do not match this hosted web app and contest sandbox boundary. If code is copied, keep required Apache notices and exclude separately licensed paths.

### OpenClaw Voice Call Realtime

[openclaw-voice-call-realtime](https://github.com/durotimmi-sk/openclaw-voice-call-realtime) is an MIT-licensed OpenClaw plugin built on Twilio Programmable Voice and OpenAI Realtime. I verified the license text, but have not audited or run its source in this workspace. It requires an OpenClaw gateway, public HTTPS webhooks, a Twilio voice number, and OpenAI Realtime credentials, so it is not a drop-in voice layer for OpsPilot or a free-key path. Borrow its call interaction ideas only after the core product works. If implemented later, the voice process must call the same OpsPilot API and permission broker as web chat; it must not gain independent browser or purchase permissions.

### User channels and integration priorities

| Channel/tool | Priority | Why |
|---|---|---|
| Web app | Required | Main control surface, evidence viewer, approvals, and judge experience. |
| MCP server/tools | Small, if time remains | A bounded way for another agent/client to start a task and retrieve status/evidence; reuse the same policy and auth. |
| Voice in browser | Optional polish | Useful for clarifying a request and supervising a run, but must share task state and permissions. Existing browser voice is cheaper to demo than phone infrastructure. |
| Phone calls | Later | OpenClaw/Twilio integration can demonstrate supplier outreach, but introduces provider keys, number/minute costs, jurisdictional rules, consent, and outbound-action risk. Only build with explicit call approval and a simulated/test recipient first. |
| WhatsApp bot | Later | Useful delivery/notification channel, not the core agent; adds provider onboarding, webhook security, message policy, and another state surface. |
| Browser extension | Later | Could send the current tab URL to OpsPilot; it is unnecessary for the required demo and expands permissions and store review surface. |
| Siri / Grok / other agent swarms | Later or exclude | Product-specific integration costs and weak contest value until the one-agent execution boundary is robust. Use one orchestrator with specialized, permission-bounded steps. |

## Free access and keys

The official event page advertises **$200 in Vultr credits for each participant** and provides a gift-code redemption path. The event's credit instructions require a valid email not previously associated with a Vultr account; register for the event, use its official gift code in Vultr Billing, and confirm the balance in the console. These credits are cloud account credit, not an unlimited or pre-made API key. Vultr Serverless Inference is usage-billed and requires provisioning a subscription and retrieving its API key; check the account's credit eligibility and live model rates before relying on the promotion to pay inference charges. Never post the key in chat or put it in browser/worker code; store it only as a server environment secret.

OpenRouter can be useful for local experimentation, but it is not the contest inference route for Challenge 1. For BLAZE or Codegeist, choose the event-required wallet/platform credentials separately; testnet or development credentials should be used until submission rules and transaction safety are clear.

The backend now has a `TASKVAULT_COMPETITION_TRACK` guard: `development` permits compatible providers for local iteration, while `blast_radius_zero` rejects model calls unless the HTTPS endpoint host is exactly `api.vultrinference.com`. Keep this set to `development` until the contest credentials exist; set it explicitly on the Challenge 1 server before rehearsing/submitting. This enforces the provider requirement but does not itself prove that Vultr credits cover inference usage.

## After the sprint: reusable product roadmap

1. **Trustworthy browser execution:** an isolated, resumable worker with policy-enforced destinations, evidence captured at the point of observation, clear stop/timeout behavior, and measured extraction accuracy.
2. **Evidence-based decisions:** normalize item variants, units, shipping, minimums, delivery and applicable taxes; report confidence and unknowns, and let buyers change scoring priorities.
3. **Approval and audit:** risk-tier actions, approval expiry, idempotency, immutable event history, and a clear account of actions blocked or never attempted.
4. **Conversational operations:** same task can be started, clarified, interrupted, resumed, and checked over text or voice; no channel bypasses policy.
5. **Supplier performance memory:** calculate observed quote responsiveness and delivery/quality outcomes only from user-confirmed events, with sample size and time window.
6. **Market-specific localization:** only after selecting a buyer segment and geography; support currency, tax, terminology, sourcing constraints, and compliant sources as configuration.
7. **Integrations:** MCP first for a controlled tool interface; then Jira/Confluence Forge for Codegeist; then messaging/phone channels if user demand and economics justify them.

## Event links and last checked

- [Vultr Agent Rush official event brief](https://community.vultr.com/e/vultr-agent-rush-hackathon) and [LabLab live dashboard](https://lablab.ai/ai-hackathons/vultr-hackathon/live)
- [Vultr Agent Rush submission/credit page](https://lablab.build/ai-hackathons/vultr-hackathon?enroll=true)
- [Vultr Serverless Inference provisioning](https://docs.vultr.com/products/compute/serverless-inference/provisioning)
- [BCH BLAZE official site](https://bchblaze.com/) and [official bounties](https://bchblaze.com/bounties/)
- [Atlassian Codegeist 2026 official listing and rules](https://codegeist2026.devpost.com/rules)

Checked 2026-11-06. Recheck event dates, rules, model rates, and credit conditions before acting; these can change.
