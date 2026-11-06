# Product

## Register

product

## Users

Procurement operators at organizations that buy recurring goods or services. The first industry, buyer segment, and geography are open decisions to validate against the hackathon brief and buyer discovery. They need to compare suppliers and justify a purchase without turning every request into a spreadsheet exercise.

The operator is accountable for spend but does not want an autonomous agent placing orders. They need speed, traceability, and a clear human checkpoint.

## Product Purpose

OpsPilot turns an operations request into a defensible result. The current first workflow is procurement sourcing:

1. Parse the product, quantity, and unit from natural language.
2. Compare supplier offers on landed cost, lead time, rating, minimum order, and verification.
3. Keep an inspectable evidence record behind every number.
4. Draft the quote request or purchase order without sending it.
5. Record a human approval decision before any external action.
6. Preserve an audit trail of what the agent did and what it did not do.

Success means the operator can answer: what did the agent actually do, what evidence supports the recommendation, what remains uncertain, and what still requires my approval?

## Market hypothesis

No city, country, currency, or first industry is selected as the product's target market. Do not pitch OpsPilot as a Lagos or Nigeria-specific project. The bundled demonstration catalog is illustrative and USD-denominated; it is not evidence of live coverage or the eventual target market. Select an initial buyer workflow from the hackathon's problem statement and validate it with users before localizing suppliers, taxes, delivery rules, or currency.

OpsPilot should be positioned as a permission-aware operations agent. Its first workflow is a vendor-neutral buying decision workspace that turns competing offers into a comparable, explainable decision a buyer can defend later.

## Differentiation to earn

- Fresh, attributable quotes with a visible source, capture time, expiry, and a clear stale state.
- Correct comparison of equivalent products, units, and pack sizes, with delivery, taxes, duties, and minimum quantities separated from base price where relevant.
- Product or compliance document checks linked to authoritative records. A document check must never be described as verification of the seller or a guarantee of product quality.
- A reasoned recommendation that states its trade-offs and lets the buyer change priorities such as lowest landed cost, shortest delivery, or approved documentation.
- A buyer-controlled record from request through quote, approval, purchase, receipt, and actual delivery performance.

The defensible advantage would be the history of verified quotes and observed supplier performance, with buyer permission. A chat interface or generic agent is not a durable differentiator by itself.

## Competitive framing and product bet

Current public product material shows that guided purchasing intake and AI supplier discovery are already offered by established procurement products. Fairmarkit describes supplier matching, response probability, sourcing events, alternatives, and supplier-performance data; Procurify's Guided Intake creates policy-aware order requests. Sabi describes a broad African B2B marketplace and distribution/logistics offering. OpsPilot should not compete on “we have an AI agent” or on a comparison table alone. The available product descriptions do not establish that Sabi targets clinic medical consumables specifically; that is an open market question.

The product bet is **Voice-to-Verified-Quote with receipts**: a buyer can talk through an incomplete request naturally, answer follow-up questions, and ask the assistant to start or supervise a sourcing run. The voice session uses the same conversation history, task state, evidence rules, and approval controls as typed chat. It can clarify product specifications, quantity, delivery destination, budget, or urgency; explain trade-offs; recover after a failed run; and resume a saved task. It must say when a result is sample data or stale. Voice does not itself contact a supplier or place an order. Future supplier outreach should be a separately approved action with recorded supplier-stated terms and timestamps.

The durable loop is quote → approved order → received goods → buyer-confirmed quality and delivery. Supplier reliability must be calculated from those observed buyer outcomes and shown with sample size and uncertainty; marketing claims and model inference stay separate. A “Siri-like” voice interface should be a faster way to start and supervise the same controlled workflow, not a second agent with broader permissions.

## Hackathon submission plan

### One-sentence pitch

OpsPilot takes a natural-language operations task, performs bounded work in an isolated environment, and returns evidence a person can verify before approving any consequential action.

See [HACKATHONS.md](./HACKATHONS.md) for the dated event plan, Vultr Agent Rush requirements, reuse audit, free-credit path, and channel priorities. The immediate event plan is geography-neutral and specifically targets Vultr's Blast Radius Zero challenge.

### Demo path

1. Start with a natural-language or voice request that is missing a useful detail. Ask a focused follow-up rather than guessing.
2. Search a bounded set of approved sources and show which sources were actually reached.
3. Extract offers with source links, capture times, price units, pack sizes, delivery, minimums, and missing fields visible.
4. Compare equivalent offers using an explicit total-cost calculation. Show trade-offs and uncertainty beside the recommendation.
5. Open a receipt for the evidence behind a price, and show stale or unverified information as such.
6. Draft an RFQ or order for review. Require an explicit approval before any external contact or purchase; record the decision in the audit trail.
7. Reload or recover a failed run and show that the conversation and task state resume. Voice must use this same task and evidence path.

Use a single buyer workflow chosen from the event brief. The demo can use clearly labeled fixtures while integrations are incomplete, but must never present fixture data as live supplier research.

### What should make it stand out

- **Receipts, not confident prose:** every ranked factual value points to a source and observation time.
- **Comparable totals:** normalize units and pack sizes before ranking; make shipping, tax, duties, minimum order, and exclusions visible.
- **Useful uncertainty:** show unknown, stale, conflicting, and unverified fields; never invent a missing value to complete a table.
- **A real agent boundary:** browsing is isolated and domain-limited; user data and provider keys stay outside the worker.
- **Human-owned consequences:** sending, calling, ordering, and payment stay disabled unless a future integration has a distinct approval step and records what actually happened.
- **Operational recovery:** show real queued/running/completed/failed/stopped states, retry or resume behavior, and an inspectable audit history.
- **Voice as an interface to the same workflow:** it clarifies and supervises the task instead of acting as a separate, more privileged agent.
- **Earned supplier intelligence:** reliability comes from buyer-confirmed quote and fulfillment outcomes with sample counts, not model-generated ratings.

### Evidence judges should be able to inspect

- A live or reproducible demonstration of at least three comparable offers, with receipts for every price used in ranking.
- A manually checked evaluation set covering ambiguous requests, pack-size mismatches, missing prices, contradictory sources, stale data, timeouts, and prompt injection in supplier pages.
- Reported extraction and total-cost accuracy with the test count and known limits. Do not claim accuracy figures without the underlying test results.
- A containment receipt showing the worker's network and filesystem boundary, plus a check that credentials and database files are not available inside it.
- A failed or interrupted run that recovers honestly, and an approval attempt that cannot trigger an unapproved external action.
- A concise architecture and data-handling explanation, a working demo URL, a short demo video, and a README that clearly separates implemented features from roadmap items.

### Decisions still open

- The initial buyer, industry, geography, currency, and source set. These must come from the event brief and user validation, not an assumed city or country.
- The initial post-hackathon inference provider and model, after checking provider terms, data handling, and rate limits. Vultr Serverless Inference is the required Challenge 1 route for Agent Rush.

Until these are settled, keep the core procurement workflow configurable and use synthetic or explicitly illustrative data. Never put an API key in browser code, a public repository, or the chat.

## Build sequence

1. **Deploy the first operator instance on Contabo:** serve the frontend and Python API from one same-origin Nginx site, with an isolated system user and SQLite database. Use a temporary single-operator access gate, HTTPS, backups, and health checks; implement native authentication and tenant isolation before onboarding other organizations. Conversation turns and task results persist server-side and the active thread restores after reload in the same browser.
2. **Replace sample sourcing with a contained research worker:** use Linux Bubblewrap without Docker, restricted outbound domains, strict time/resource limits, and no app database, credentials, or user home mount. The first server run still evaluates the bundled sample catalog; live supplier browsing needs an egress allowlist, real evidence capture, and source verification before activation.
3. **Make every result provable:** emit real run events, capture page screenshots and source URLs, bind extracted fields to those receipts, label capture time and stale quotes, and block uncited fields from ranking. Exercise hostile page instructions, timeouts, resource limits, cancellation, and worker teardown before enabling live research.
4. **Make real supplier quotes usable:** choose a buyer segment and market from the hackathon brief and discovery, then normalize product specifications, pack sizes, destination, currency, delivery, taxes, and minimums for that market. Draft RFQs from approved templates, require buyer approval before any contact, and parse replies into the same evidence-backed quote schema.
5. **Build conversational voice:** hold a context-aware voice session across turns, let the user interrupt speech, surface live transcripts and task progress, route requests through the same task/permission layer, and preserve recoverable session state. Start with browser speech services and a clear capability label; add low-latency streaming after backend inference and task tools are operational. Keep approvals visible and require explicit confirmation for consequential actions.
6. **Earn supplier intelligence:** after buyers record receipts, report on-time delivery, fill rate, quality issues, quote responsiveness, and price variance with their sample counts and date ranges. Never fabricate missing history.

## Market sources reviewed (2026-11-05)

- [Procurify Guided Intake](https://www.procurify.com/changelog/guided-intake/) describes policy-aware AI order-request intake.
- [Fairmarkit Supplier Discovery Agent](https://www.fairmarkit.com/platform/supplier-discovery-agent) describes AI supplier discovery, alternatives, response probability, and supplier intelligence.
- [Sabi](https://sabi.am/) describes a B2B marketplace plus sourcing, distribution, and logistics across African markets.
- [Twilio Conversation Relay](https://www.twilio.com/docs/voice/conversationrelay) provides a WebSocket voice-agent path; its [best practices](https://www.twilio.com/docs/voice/conversationrelay/best-practices) include reconnect and echo-filtering considerations.
- [Twilio recording guidance](https://help.twilio.com/articles/360011522553) explains that recording-consent requirements vary by jurisdiction and that customers must manage consent and retention.
- [Twilio's Voice API](https://www.twilio.com/docs/voice/api/call-resource) can initiate outbound calls. Check destination pricing, number availability, support, and regulatory requirements for the selected market before choosing a provider.

## Current capabilities

- Chat-led demonstration for seven product categories with 21 illustrative supplier records. They are not real supplier quotes.
- Quantity normalization across pieces, boxes, and cartons.
- Landed-cost comparison with shipping thresholds, MOQ, lead time, rating, and verification status.
- Local evidence pages for every offer, explicitly marked as bundle records rather than live captures.
- Sourcing worker in macOS Seatbelt mode, Docker mode when available, or an explicitly weaker process fallback; each run includes a containment receipt.
- Price watches checked against stored evidence.
- Quote-request and purchase-order drafts with an approval threshold.
- Human approve/reject decisions recorded in the audit ledger.
- Buyer profile with ship-to, budget, threshold, and payment preference. No card data is collected.
- Browser voice input and output; currently limited by browser speech services and the configured inference backend.
- Saved conversation turns linked to research tasks, with same-browser restore after reload. The hosted single-operator session gate does not add tenant isolation or cross-device ownership controls.
- MCP tools for sourcing, results, watches, approvals, and the audit ledger.
- A configurable OpenAI-compatible inference endpoint for general chat and an optional research narrative. No provider credentials are currently configured on the deployed instance.

## Honest boundaries

OpsPilot does **not** currently:

- crawl live supplier websites or run a browser worker;
- fetch user-provided URLs (they are shown as unvisited references and do not affect ranking);
- verify a supplier page at request time;
- schedule automatic price checks or send push/email alerts;
- send supplier messages, place calls, or place orders;
- process payments or collect card numbers;
- provide multi-user authentication, authorization, or tenant isolation. The hosted single-operator sign-in is only an access gate.

The supplier catalog is demonstration data shipped with the repository. Supplier names, locations, prices, ratings, certifications, and verification flags are illustrative. The UI, assistant, and evidence pages must say so. A sample ranking is not a buying recommendation or a live market quote.

The current prototype is not ready for real procurement in any target market: it has no live supplier records, market-specific currency, taxes, delivery model, product verification sources, or multi-user customer authentication.

## Jobs to be done

- "I need 500 boxes of nitrile gloves this week; which supplier is actually cheapest after shipping?"
- "Show me why this supplier is ranked first and where the number came from."
- "Draft the quote request, but do not send it until I review it."
- "Watch this price and tell me when the stored price reaches my target."
- "What was the lead time and MOQ on the option I approved?"
- "Let me ask by voice while I am away from the keyboard."

## Product principles

1. **Evidence before confidence.** Every price, rating, and lead time has a source, a timestamp, and a freshness state. Sample data is labeled as sample data.
2. **State is explicit.** Queued, running, completed, failed, stopped, pending approval, approved, and rejected are real backend states.
3. **Humans own consequences.** Drafts are drafts. Approval records a decision; it does not silently execute.
4. **Uncertainty stays visible.** Unverified suppliers, stale quotes, missing fields, and process-mode limitations are labeled.
5. **No invented progress.** The loader reflects task events, not a scripted animation.
6. **Calm under pressure.** A neutral hierarchy, readable numbers, and one clear next action.

## Anti-references

- Generic AI dashboards with decorative gradients and glowing cards.
- Fake supplier results, invented stock, fabricated reviews, or simulated browsing.
- An agent that claims to have sent, called, ordered, or paid when it only wrote a draft.
- A mascot that competes with evidence or implies work that did not happen.
- Generic agent readiness widgets that repeat the conversation without showing decision-relevant context.

## Key flows

### Source

Ask for a product and quantity → task is created → isolated worker computes offers → result shows rank, landed cost, lead time, rating, MOQ, verification, and evidence → open an evidence record or create a watch/draft.

### Approve

Open a draft quote or purchase order → review the exact body and amount → approve or reject → the decision is recorded in the audit ledger. Nothing is sent or charged.

### Watch

Choose an offer and target price → watch stores the target and latest evidence price → manual check updates status → a triggered watch says to review the supplier before acting.

### Voice

Start a voice session → explain the need naturally → the assistant asks for missing constraints → it starts the same sourcing task as typed chat → the user can interrupt, ask about progress, recover from an error, or continue with a follow-up → speech output reads the grounded response. The session must not imply unsupported live browsing or external actions.

## Success signals

- A first-time user can complete a sourcing request and explain the recommendation without opening the catalog file.
- Every recommendation exposes at least one trade-off or uncertainty when it exists.
- No flow implies an external action that did not occur.
- The containment test passes with no inherited database path or inference key.
- The audit chain validates after a normal end-to-end session.
- A buyer can compare at least two current quotes for the same pack size and see what makes the recommendation win.
- The delivered price and promised lead time can be compared with the quote and recorded at receipt.

## Accessibility and inclusion

Keyboard access, visible focus, readable contrast, responsive layout, reduced-motion support, and state labels that do not depend on color or animation alone. Small text is never used for prices, evidence status, or approval decisions.
