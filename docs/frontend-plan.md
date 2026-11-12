# Frontend work list (`static/index.html`)

Status: written 2026-11-11. **Part A is done except A9 (2026-11-12); Part B: B1 and B3 done, B2 skipped (2026-11-12).** One static HTML file with vanilla JavaScript stays the
rule (`CLAUDE.md`). When an item is done, its facts move to `docs/implementation.md` and it is ticked here.

The list has two parts, because they are done by different means:

- **Part A, behaviour**: what the page must *do*. Plain JavaScript wiring, verified by clicking through the
  flow. No visual decisions beyond reusing the existing classes.
- **Part B, design**: how the page *looks and reads*. Done with the Impeccable skill, as `CLAUDE.md` requires.
  Impeccable is installed in `.claude/skills/impeccable/`.

Order: Part A first, then Part B. Impeccable's `craft` should restyle a page that already contains every
element, otherwise elements added later would not follow `DESIGN.md`.

## Must stay (payment behaviour and trust cues)

Whatever changes, these remain visible and unchanged in meaning:

- The "Confirm and pay with PayPal" button, disabled after one click.
- "Nothing is charged until you approve the payment on PayPal."
- The total in the order summary, always the server's number. The page never adds prices.
- The mock-mode badges.
- The "Ruled out" list with the reason for each product.
- "Nothing is refunded until you click Confirm refund." and the Confirm refund button.
- The concierge-simulation sentence at the top.
- Product text is written with `textContent` only, never as HTML.

## Part A: behaviour (no design tool needed)

A1. **Waiting message. DONE 2026-11-12** as real progress instead of a fixed text: the page polls
    `GET /api/progress` once a second and shows the agent's current step. See `docs/implementation.md`
    ("Agent progress shown while the page waits"). Part B still has to style the waiting bubble.

A2. [done] **No double send.** Pressing Enter while a request is running sends a second message: only the button
    is disabled, the form still submits. Ignore submits while one is running.

A3. [done] **Example buttons** under the input, each sends its text as a chat message:
    `a tent, a sleeping bag and a lantern under $300`, `I always buy Sony`, `my orders`.
    Shown only while the conversation is empty.

A4. [done] **Refund buttons on an order card.** "Refund this item" on every line not refunded, and "Refund the rest"
    when more than one line is left. They send `refund item N of order X` / `refund order X` to the chat, so
    the agent still drafts the refund (F16, F23) and money moves only on Confirm refund. Shown only for
    `COMPLETED` and `PARTIALLY_REFUNDED` orders.

A5. [done] **Compact order list.** When a reply carries more than one order, draw one line per order (ID, status,
    amount, items) instead of a full card each. A single order keeps the full card.

A6. [done] **After-payment note.** On the result card of a paid order: this is a sandbox simulation, nothing
    ships, and the order can be checked or refunded here.

A7. [done] **Product images.** Recommendations and set options carry an `image` URL that the page never shows.
    Show a small image on each card, with empty `alt` (the title is next to it) and a fixed size so the
    layout does not jump. Skip it when the URL is empty (mock catalog).

A8. [done] **Errors read as errors.** Failures are shown as a normal bot bubble starting with "Error:". Give them
    their own class so they can be styled as errors in Part B, and keep the server's message.

A9. **Chat survives the PayPal round trip (optional, needs one endpoint).** After paying, the page reloads
    and the conversation is gone from the screen, although the server still has it. Restoring it needs a
    read-only `GET /api/history`. Not page-only, so it needs the owner's OK; skip if time is short.

Verification for Part A: `pytest` still passes (`test_page_states_concierge_simulation_and_trust_cues`
checks the trust cues), then by hand in keyless mode and once with real keys: every button, a set
purchase, a line refund through the buttons, and the page at 375 px width.

## Part B: design (Impeccable)

Budget from `CLAUDE.md`: about 2 hours in total. If time is short: `init`, `craft`, `audit` only.
No effect commands (`animate`, `delight`, `overdrive`, `bolder`).

B1. [done 2026-11-12] `/impeccable init` once: writes `PRODUCT.md` only (this version of Impeccable does not
    write `DESIGN.md` in init; `craft` writes it when it builds the page). Inputs given: a shopping agent for a
    hackathon demo, clarity over decoration, the "Must stay" list above, one static file, phone-width use.

B2. [skipped: the look was chosen in comparison rounds instead] `/impeccable shape`: layout and interaction plan for the chat page (skip when short of time).

B3. [done 2026-11-12, see `docs/implementation.md` "Page design and the Orders view"; added the owner-approved Orders view and `GET /api/orders`] `/impeccable craft`: restyle the page; `DESIGN.md` is written from the result. Things to hand it explicitly:
    - visual hierarchy between chat bubbles, product cards, the set groups, the order summary, the refund
      draft and order cards, which today all look alike;
    - the set view: chosen product versus alternatives, the total line, the "Review this set" button;
    - the order summary and refund draft as the two places where money is about to move;
    - status styling for orders (`COMPLETED`, `PARTIALLY_REFUNDED`, `REFUNDED`, `CANCELLED`, failures);
    - the waiting state from A1 and the error style from A8;
    - the "What I remember" panel and the mock badges.

B4. `/impeccable audit` before deploying: accessibility, performance, phone width. Known things for it to check:
    - the chat log has no live region, so a screen reader is not told when a reply arrives;
    - the text input has a placeholder but no label;
    - the set's radio buttons: confirm each one is announced by its product title and price;
    - colour contrast of the grey notes and the yellow badges;
    - focus order after a reply, and visible focus on every button;
    - `favicon.ico` returns 404.

B5. `/impeccable polish`: a last pass before recording the video.

After every Impeccable step: run `pytest`, click the purchase and refund flow once, and check the
"Must stay" list item by item.

## Not planned

- A frontend framework or a build step.
- Shipping or tracking displays (out of scope; nothing ships in the simulation).
- "View at retailer" links (deferred with the commission disclosure, see `docs/progress.md`).
- A size or colour picker for product variants (deferred, see `docs/progress.md`).
- Page-side price arithmetic of any kind.
