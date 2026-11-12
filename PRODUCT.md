# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Hackathon judges (PayPal AI Hackathon 2026) and recruiters. Each tries the product once, on a desktop or a phone, and most first see it in a demo video under 3 minutes. They are not shopping for real: they are judging whether the agent picks sensibly, whether its reasoning is visible, and whether money can only move when a person approves it. The project is also the owner's portfolio piece, so it must survive close inspection in interviews.

## Product Purpose

A conversational shopping agent. The user describes a need in one sentence; the agent recommends 3 products, each with a price and a one-sentence reason, or, for a request naming several items under one budget, a set whose total fits that budget. The user reviews a server-priced order summary and pays through the PayPal sandbox. Later the user can check an order or refund it line by line. The agent can also remember lasting shopping preferences, which the user can see and delete.

Success: a first-time visitor completes request, recommendation, confirmation, sandbox payment and refund without help, and understands at each step why the agent chose what it chose and that nothing moved without their click.

## Positioning

What the page itself should make a judge remember (confirmed by the owner, 2026-11-12):

1. **Transparent reasoning.** Every recommendation has a reason, and the products that were ruled out are listed with the reason for each.
2. **Payment only after human approval.** The model cannot move money. Totals are computed by the server; a PayPal order is created only after the user clicks confirm; a refund is sent only after the user clicks Confirm refund.
3. **Sets under one budget.** One sentence can buy several items whose combined total stays within the budget, and the order can be refunded item by item.

The project's main differentiator overall is its evaluation data on recommendation quality, but that lives in the README; the page does not show eval numbers.

## Operating Context

- A single chat page. Flow: request, (one budget question if none was given), 3 recommendations or a set, refine, order summary, "Confirm and pay with PayPal", PayPal sandbox approval page, return and capture, result card, later order status and refund draft.
- Concierge-style simulation: products come from outside retailers (Channel3 search), but payment goes to this project's own PayPal sandbox merchant account. No real money moves and nothing ships.
- Without API keys, the model, the catalog and PayPal each fall back to a mock, shown with mock-mode badges, and the whole flow can still be clicked through. The mock catalog has no product pictures.
- Deployed on a Render free instance: the first request after idle is slow, and a restart loses sessions, orders and preferences.
- The agent's current step is shown live while it works (polled from `GET /api/progress`).

## Capabilities and Constraints

- One static file, `static/index.html`, with vanilla JavaScript. No framework, no build step, no external fonts, no icon libraries.
- Product titles and descriptions are untrusted data and are written with `textContent` only, never as HTML.
- The page never computes a price; every amount shown is the server's number in integer cents.
- Order statuses the page shows: `COMPLETED`, `PARTIALLY_REFUNDED`, `REFUNDED`, `CANCELLED`, and failures.
- Payment trust cues that must stay visible with this exact text and meaning:
  - the "Confirm and pay with PayPal" button (disabled after one click) and "Nothing is charged until you approve the payment on PayPal."
  - the order total, always the server's number
  - the refund draft with "Nothing is refunded until you click Confirm refund." and its Confirm refund button
  - the concierge-simulation sentence at the top ("no real money moves and nothing ships")
  - the mock-mode badges
  - the "Ruled out" list with the reason for each product
- Information that must be easy to find: the notice bar with the simulation sentence and mock badges; live progress and errors that read as errors; "What I remember" with a Delete button per entry, always reachable; example requests for a first-time user; order status with refunded lines clearly marked.
- Out of scope: shipping or tracking displays, retailer links, size or colour pickers, user accounts.

## Brand Commitments

Binding constraints from the owner (recorded, not expanded):

- Name shown on the page: "Shopping Agent". A small original mark for it as inline SVG is allowed.
- It should feel at home next to a PayPal checkout (deep navy and bright blue as the accent family, white cards on a very light grey background, rounded buttons, amounts easy to scan) but must **not** imitate PayPal: no PayPal logo or wordmark, no PayPal Sans, nothing that makes it look like an official PayPal page. It is a third-party demo that only pays through PayPal.
- System font stack.
- Polished and modern, with its own visual identity, yet nothing decorative may compete with prices, totals, or the payment and refund steps.
- Motion: only subtle hover, focus and state transitions (about 150 ms). No entrance animations or effects. Effect commands (`animate`, `delight`, `overdrive`, `bolder`) are not used unless the owner asks.
- All UI text is in English.

## Evidence on Hand

- Product pictures come from the Channel3 catalog (https URLs only); the mock catalog has none, so layouts must work without them.
- Eval results exist only from actual runs and are reported in the README. Never invent numbers, testimonials, users or partner claims on the page.

## Product Principles

1. Show the reasoning: a recommendation without its reason, or a rejection without its cause, is incomplete.
2. Money moves only on a visible human click, and the page says so at the moment it matters.
3. The server's numbers are the only numbers.
4. Honest about being a simulation: mock modes and the concierge nature are always visible, never hidden for polish.
5. Clarity over decoration: every visual choice must make the flow easier to follow or more trustworthy.

## Accessibility & Inclusion

WCAG AA contrast. Works at 375 px width. Visible focus on every control. Known gaps to fix: the chat log has no live region, the text input has no label, and the set's radio buttons must be announced by product title and price.
