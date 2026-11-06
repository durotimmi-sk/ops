---
name: TaskVault
description: Evidence-first procurement operations workspace with controlled execution.
colors:
  ink: "#0d0d0d"
  ink-soft: "#3f3f3f"
  muted: "#6e6e6e"
  faint: "#9a9a9a"
  paper: "#ffffff"
  sidebar: "#f9f9f9"
  surface-muted: "#f4f4f4"
  surface-hover: "#f2f2f2"
  hairline: "rgba(0, 0, 0, 0.1)"
  hairline-strong: "rgba(0, 0, 0, 0.18)"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(28px, 3.4vw, 36px)"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.035em"
  heading:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "27px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.03em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.02em"
rounded:
  control: "9px"
  panel: "14px"
  overlay: "18px"
  mark: "17px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "16px"
  lg: "24px"
  xl: "36px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "36px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  panel:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.panel}"
    padding: "18px"
  composer:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.panel}"
    padding: "10px 12px"
---

## Overview

TaskVault is an operational tool, not a marketing surface. The desktop workspace has three regions: a collapsible navigation rail, a focused work canvas, and a collapsible procurement context rail. Both rails can be hidden independently so the user can give the task more room. On narrow screens, navigation and procurement context become separate drawers.

The interface uses restrained neutral surfaces with color reserved for the TaskVault identity, the mascot, and labeled task states. Hierarchy comes from type weight, spacing, surface tone, and hairline rules rather than gradients or elevation. The colored mascot appears beside assistant messages and animates only while work is actually processing.

The interface must make the boundary between stored evidence and live reality obvious. A supplier card can look precise, but every number must be traceable to an evidence record, and every draft must say that nothing was sent or paid.

## Layout

- **Navigation rail:** 264px rounded panel inset 10px from the viewport. Brand, primary destinations, recent tasks, account action, and sandbox state. It collapses to a 64px icon rail with accessible names and tooltips, and becomes a drawer below 860px.
- **Topbar:** 56px. View title and independent navigation/context controls. The work canvas starts below it; messages never sit behind the topbar.
- **Procurement context rail:** 316px on wide desktop. Shows agent identity, task progress, current decision context, and price watch. It collapses independently and becomes a drawer below 1181px.
- **Conversation canvas:** a rounded white panel inset 10px from the viewport, with content capped at 820px and 28px side padding. The composer is a flex sibling below the scroll area, not an overlay, so the last message is never hidden behind it.
- **Composer:** maximum 780px, one rounded field, icon-only attach and voice controls, and a single send action. No toolbar clutter.
- **Utility views:** Tasks, Price watch, Approvals, Activity, and Connections share a utility header and a 1080px content width. They are destinations, not modals stacked on the chat.
- **Overlays:** centered dialogs for drafts, source confirmation, watches, and notices. One task at a time; dismiss with Escape or the close control.

## Color

Use white for the canvas, `#f9f9f9` for the sidebar, `#efefed` for the backdrop, and `#f4f4f4` for quiet wells. Most boundaries are `rgba(0,0,0,.1)` hairlines. The primary action is ink on white; selected navigation uses a slightly stronger surface, not a colored fill. Rounded corners are structural: the page and sidebar are 18px panels, not full-bleed rectangles.

Semantic states may use restrained color, but must carry a readable label or icon. Never rely on hue alone. Do not put decorative pointer or dot graphics beside the sandbox status text. The interface has no dark theme and no bronze/gold accent. Do not reintroduce gradients, glows, or colored shadows to make it feel "AI".

Keep the mascot in color. Its working GIF is shown only while an assistant response is being generated; respect reduced-motion preferences. Do not use the mascot to imply browser work that the backend did not perform.

## Typography

Use the platform system sans stack. The 28–36px welcome heading is the largest type. Body copy is 15px with a 1.5 line height. Utility headings are 27px. Labels and metadata are 11–12px; never use small text for prices, evidence status, approval state, or errors.

Numbers use tabular figures where available. Product names, supplier names, and prices are the visual anchors in cards. Keep prose near 65–75 characters per line.

## Elevation and shape

Prefer flat surfaces and hairlines. The only meaningful shadows are on overlays and the mobile drawer. Radius scale: 9px controls, 14px panels, 18px overlays. Avoid nested cards; a research result should read as one coherent answer with internal rows, not a stack of boxes.

## Components

- **Welcome:** the colored mascot, one clear headline, a short explanation, and suggestion rows. Suggestions demonstrate real supported requests, not fake capabilities.
- **Message:** user messages align right on a soft grey bubble; assistant messages align left and use the full measure. The mascot sits beside assistant replies in a 32px light tile, sized and marked eager so it is visible rather than blending into a black square.
- **Run state:** a single inline loader with a stage label, elapsed stage activity, and expandable evidence links. It must be driven by backend task state, not a frontend timer that invents progress.
- **Research result:** recommendation headline, summary, rank rows with supplier, price, lead time, rating, MOQ, verification, and actions. Offer rows expose evidence and draft/watch actions without hiding uncertainty. Buyer-provided URLs appear after the summary under “Links you added · not opened”; they are references only, not fetched sources or ranking evidence.
- **Evidence record:** `/sources/{id}` is a plain, printable HTML page with the listing values, capture time, and an explicit "not a live page capture" note. It uses the same monochrome tokens and no scripts.
- **Drafts:** the quote/PO dialog shows the exact text, amount, approval threshold, and the fact that no message or order has been sent. Approval is a recorded human decision, not a payment.
- **Tasks:** history with status, intent, stage, and result preview. Selecting a task restores the conversation and evidence.
- **Price watch:** supplier, target, current stored price, last check, and status. A check is manual; do not imply a background monitor.
- **Approvals:** pending and decided drafts with the full body, amount, and decision note. Empty states explain how to create one.
- **Activity:** chronological ledger with event kind, message, and chain validity. No unread badges without a real notification source.
- **Connections:** model readiness, sandbox mode, containment test, and the MCP configuration snippet. Seatbelt and Docker modes must report network denial; process mode must disclose host network access.
- **Voice overlay:** a centered listening/speaking surface with transcript, stop control, and a text fallback. Speech recognition is browser-provided and may leave the device; say so in the UI.
- **Mobile:** navigation and procurement context become separate rounded drawers with backdrops. The composer remains reachable above the safe area.

## Motion

Motion is functional and short. Use 120–180ms ease transitions for hover, focus, drawer, and dialog entry. The loader may pulse; the mascot halo may orbit while generating or speaking. Respect `prefers-reduced-motion` by removing orbit/rotation and keeping a static emphasis. Never animate numbers, prices, or evidence into view in a way that suggests a live update.

## Voice

Voice is an interaction layer over the same task evidence and chat history. Keep the session open between turns, show the transcript and current processing state, and resume listening after the response. It does not call suppliers or send messages. Speech recognition is browser-provided and may leave the device; disclose this in the interface.

## Content rules

- Say "bundled supplier index", "evidence record", "draft", "approval", and "stored price" precisely.
- Do not say "live", "scraped", "verified today", or "ordered" unless the corresponding evidence and action exist.
- Every recommendation includes at least one uncertainty or trade-off when it exists.
- Empty and error states explain the next safe action.
- Backend failures use a dialog, not a silent inline status or a fake assistant answer.

## Accessibility

- Full keyboard operation with visible focus rings that do not rely on color.
- Native select controls are replaced with a muted chevron and a visible focus ring; no black platform arrow is left to clash with the interface.
- Dialog focus trap, Escape to close, and focus return to the trigger.
- Live regions for task status and voice transcripts.
- Minimum 44px touch targets on mobile.
- Text contrast of at least 4.5:1 for body copy and 3:1 for large text.
- Semantic headings, labels, and button names; no icon-only control without an accessible name.
- Reduced-motion support; no parallax, autoplay audio, or animation required to understand state.

## Do's and Don'ts

- Do keep evidence, supplier identity, and uncertainty close to every claim.
- Do distinguish macOS Seatbelt, Docker, and process fallback in receipts and UI.
- Do require a human checkpoint before messages, calls, orders, or payments.
- Do show the exact draft and amount before approval.
- Don't invent supplier counts, prices, stock, reviews, or completion states.
- Don't imply that a bundle lookup is a live page visit.
- Don't use the mascot as proof of work or as a permanent glow.
- Don't add a second accent color to compensate for weak hierarchy.
