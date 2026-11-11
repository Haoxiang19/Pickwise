# Plan: buying several products in one order (F21, F22, F23)

Status: planned on 2026-11-11, **not started**. This file is a work order for whoever implements it.
It describes what to build and in which order. When the work is done, the facts move to
`docs/implementation.md` and this file is deleted.

Read `CLAUDE.md`, `docs/requirements.md` and `docs/progress.md` first. Every rule in `CLAUDE.md`
applies, in particular "Rules that must not be broken".

## 1. Goal

Today the agent recommends 3 alternatives for one need, a cart holds one product, PayPal receives
only a total, and a refund is always the whole order. Three additions:

- **F21 Multi-item cart.** A cart holds up to 6 different products. The server computes the total and
  refuses the cart if the total is over the budget. PayPal receives the line items with the total.
- **F22 Set recommendation.** When the user asks for several different products under one total
  budget ("a tent, a sleeping bag and a lantern under $300"), the agent searches each item
  separately, ranks each item with the existing shuffled ranking, and **code** picks the best set
  whose total fits the budget.
- **F23 Refund by line.** The user can refund one product of a paid order, or all of it.

F21 is useful alone (two searches, one payment). F22 and F23 both need F21.

## 2. Decisions already taken by the owner

- **Code builds the set, not the model.** The model splits the request into items (step 1), ranks
  each item (step 4) and writes the reply. Choosing which products go together is arithmetic on
  prices against a budget, and the budget is checked in code (`CLAUDE.md`).
- Each item keeps the existing ranking output: at most 6 ranked products (`MAX_RANKED`). Each item
  has at most 6 options in the set search. Do not change `MAX_RANKED`.
- Multi-shuffle ranking stays on for sets (`rank_shuffles` from the flags, default 3).
- The budget is a constraint and the rank is the objective. The set is **not** chosen to be close to the budget.
- The model never splits the budget between items. Code computes each item's limit.
- **The number of items follows the user's request, up to a technical ceiling of 6 items per set and
  6 lines per cart.** With 6 options per item that is 6^6 = 46,656 sets to enumerate, 12 searches and
  18 parallel ranking calls for one request. Above the ceiling the tool returns an error that tells
  the model to ask the user to split the request.
- **PayPal receives the line items** (`purchase_units[0].items` with `amount.breakdown.item_total`).
- **A paid order can be refunded line by line.**

Chosen by the planner, the owner may change them before work starts:

- 1 to 2 search queries per item.
- A refund covers a whole line (every unit of that product), not single units of a line.
- No set requests are added to the eval. Unit tests only. The README says that set recommendation has no eval numbers.

## 3. Requirement text to add to `docs/requirements.md`

Section 3: take "multiple items per order" out of the P2 sentence and add this table under P2.

| ID | Feature | Acceptance criteria |
| --- | --- | --- |
| F21 | Multi-item cart | A cart holds 1 to 6 different products, each with a quantity; the total is the sum computed by the server in integer cents; a total over the budget refuses the whole cart; one unknown, unavailable or duplicate product refuses the whole cart; the PayPal order carries one line item per product and an item total equal to the amount |
| F22 | Set recommendation | For a request naming 2 to 6 different products under one budget, each item is searched and ranked on its own; code picks the set with the lowest rank sum among sets whose total is within the budget; if no set can fit, no model ranking is run and the user is told the price of the cheapest set |
| F23 | Refund by line | The agent drafts a refund for chosen lines or for every line not yet refunded; PayPal is called only after the user confirms, once per line, for that line's amount; a refunded line cannot be refunded again; the order is `PARTIALLY_REFUNDED` until every line is refunded, then `REFUNDED` |

Other edits:

- F16: "a refunded order cannot be refunded again" becomes "a refunded line cannot be refunded again (F23)".
- Section 6: a cart may hold up to 6 products and the budget check is on the cart total. The refund
  request ID becomes `refund-{order_id}-{line}`. Refund runs from `COMPLETED` or `PARTIALLY_REFUNDED`.
- Section 7: add the status `PARTIALLY_REFUNDED`. Each entry of the order's `items` snapshot may carry a `refund_id`.
- Section 8: the create-order note gains the line items and `amount.breakdown.item_total`. The refund
  note changes from "a full refund is sent with an empty JSON body" to "every refund states its
  amount: `{"amount": {"value", "currency_code"}}`". Add both to "Verify before relying on them".

## 4. What must not change

- `recommend()` and its eval flags. The eval (`eval/`) is not touched and `tests/test_eval.py` must still pass.
- The Confirm logic, the read-back check before capture, the capture, cancel handling and the error
  mapping in `app/checkout.py`. The read-back still compares `amount.value` and `currency_code` with the order row.
- The lock, the local status checks and the deterministic request IDs for create and capture.
- Tool tiers: `recommend_bundle` is read-only; `prepare_cart` and `draft_refund` are proposals. No tool moves money.
- The page never adds prices. Every total shown comes from a server response.
- `BASE_URL` stays the sandbox constant.

Allowed changes to money code, and only these: the body of `paypal.create_order` (section 7), and
the refund path in `paypal.refund_capture`, `paypal_mock.refund_capture`, `checkout.refund_draft`
and `checkout.refund` (section 10).

## 5. Step 0: look at existing implementations, record the decision

Required by `CLAUDE.md` ("Look for credible open-source implementations first"). About 15 minutes.
Add one entry to `docs/decisions.md` covering:

- PayPal Orders v2 docs on `purchase_units[].items` and `amount.breakdown.item_total`: the required
  fields, the length limit of `name`, the type of `quantity`, and the error returned when the sums do not match.
- PayPal Payments v2 docs on refunding a capture with an `amount`: several partial refunds on one
  capture, the refund statuses, and the error when the refunds exceed the captured amount.
- One or two maintained MIT/Apache-2.0 projects with a line-item cart: how they compute the total,
  where they validate it, and how they record a refund of one line.
- Choosing one option per group under a total limit (a multiple-choice knapsack). Say why plain
  enumeration is enough here.

If what the docs say differs from sections 7 or 10, stop and ask the owner. If nothing credible is
found for a point, say so in the entry.

## 6. Commit 1: F21 Multi-item cart

`app/store.py`
- Add `MAX_CART_LINES = 6`.
- Add `create_cart_items(session, lines, now=None, fetch=None)`, where `lines` is a list of
  `(product_id, quantity)`. For every line run the checks `create_cart` runs today, in the same
  order: ID known to `session.products`, read back with `_refreshed`, in stock with a USD price,
  quantity an `int` from 1 to `MAX_QUANTITY`. Also refuse an empty list, more than `MAX_CART_LINES`
  lines, and the same product ID twice. Any failing line raises `CartError` for the whole cart.
- Total = sum of `price_cents * quantity`. If `session.budget_cents` is set and the total is above
  it, raise `CartError` with the same message as today.
- `price_was_cents` moves from the cart onto the item whose price changed.
- `create_cart(session, product_id, quantity=1, now=None, fetch=None)` stays as a wrapper that calls
  `create_cart_items` with one line, so current callers keep working.

`app/agent.py`
- `prepare_cart` keeps `product_id` and `quantity` and gains an optional `items` array of
  `{product_id, quantity}`. `tool_prepare_cart` turns either form into lines. Any price the model
  sends is still ignored.
- `cart_view` returns `{"cart_id", "items": [{"title", "quantity", "unit_price_cents", "price_was_cents"}], "total_cents", "currency"}`.
- The tool result for the model lists each title with its quantity, the total, and a price note per changed item.

`app/main.py`
- `CartIn`: `product_id` becomes optional and `items: list[CartLine] | None` is added. Exactly one of
  the two must be given, otherwise HTTP 400. `CartLine` is `{product_id: str, quantity: int = 1}`.

`static/index.html`
- `showSummary` shows one row per item (title, unit price, quantity), then the total, then one
  price-change line per changed item. The Confirm button, the "Nothing is charged until you approve"
  note and the total stay exactly as they are.

Tests
- Update the tests that read the old shape: `tests/test_store.py` (`price_was_cents`),
  `tests/test_agent.py` (`cart["title"]`, `["quantity"]`, `["unit_price_cents"]`).
- New in `tests/test_store.py`: two-line total in cents; total over budget refused although each line
  is under it; unknown ID in the second line refuses the cart; duplicate ID; seven lines; empty list;
  a price change is recorded on the right item.
- New in `tests/test_api.py`: `POST /api/cart` with `items`; both or neither field is 400; a full
  mock purchase of a two-item cart ends `COMPLETED` with both items on the order and the summed amount.

Docs in the same commit: `docs/implementation.md` (new F21 entry, updated F8 entry), the F21
requirement text from section 3, `docs/progress.md`.

## 7. Commit 2: F21 PayPal line items

This changes the create-order body for every order, single-item orders included. It is P0 payment
behaviour and has never been run against the sandbox.

`app/paypal.py`
- `create_order` gains an `items` argument (the order's item snapshot). The body becomes:
  `purchase_units[0].amount = {currency_code, value, breakdown: {item_total: {currency_code, value}}}`
  and `purchase_units[0].items = [{name, quantity, unit_amount: {currency_code, value}}]`.
  `name` is the title cut to the length limit found in step 0, `quantity` is sent as a string, and
  every value comes from integer cents through `to_dollars`.
- Before sending, check in code that the sum of `unit_price_cents * quantity` equals `amount_cents`.
  If it does not, raise `PayPalError` and send nothing. There is no tax or shipping, so the item
  total always equals the amount.

`app/checkout.py`
- `confirm` passes the order row's items to `paypal.create_order`. Nothing else in `confirm` changes.

`app/paypal_mock.py`
- `create_order` checks the same sums and raises the issue names found in step 0, so a wrong body fails in tests.

Tests
- `tests/test_paypal.py`: the body for a two-item order; quantity is a string; a long title is cut;
  a sum mismatch sends nothing.
- `tests/test_checkout.py`: Confirm sends the order's items; the existing read-back and capture tests still pass unchanged.

Docs in the same commit: update the F9/F10 entry in `docs/implementation.md`, section 8 of the
requirements, and add "line items accepted by the sandbox" to "Not verified" in `docs/progress.md`.

## 8. Commit 3: F22 core in `app/recommend.py`

Pure code plus ranking calls. Not reachable from the agent until commit 4.

Constants: `MAX_BUNDLE_ITEMS = 6`, `BUNDLE_QUERIES = 2`.

`parse_bundle(args) -> dict`
- Budget through the existing `budget_from` (so "around $300" is widened the same way).
- `items`: each has `name` (required), `queries` (cut to `BUNDLE_QUERIES`, default `[name]`),
  `quantity` (int 1 to 10, default 1), `must_have`. Fewer than 2 items or more than
  `MAX_BUNDLE_ITEMS` raises `ValueError` with a message that tells the model what to do.
- `must_not` and `preferences` apply to every item.

`best_combo(options, budget_cents) -> tuple[int, ...] | None`
- `options[i]` is the list of costs in cents (unit price x quantity) for item `i`, best rank first.
- Enumerate every set with `itertools.product`. Keep sets whose total is within the budget (all sets
  when the budget is `None`). Return the indexes of the set with the smallest
  `(sum of indexes, total cost)`. Return `None` when no set fits.

`recommend_bundle(request, flags=DEFAULT_FLAGS, search_fn=catalog.search, seed=None) -> dict`
1. **Search.** Per item, `search_all(item queries, search_fn, cap)` with `cap` = the total budget
   when `flags["budget_filter"]` is on. `over_budget_examples` is not called for sets.
2. **First filter.** `hard_filter(products, budget, must_not)` per item. An item with no candidate
   ends the run: no ranking, no set, and a note that names the item.
3. **Feasibility.** `floor[i]` = cheapest candidate cost of item `i`. If the floors add up to more
   than the budget, end the run with no ranking and a note: the cheapest set costs $X, the budget is $Y.
4. **Per-item limit.** `unit_cap[i] = (budget - sum of the other floors) // quantity[i]`. Run
   `hard_filter` again with `unit_cap[i]`. A product that is within the total budget but above the
   cap is rejected with the reason "would leave too little for the other items (at most $N for this item)".
   Keep `rejection()` itself unchanged.
5. **Rank.** Per item, `rank_shuffled` with a request built for that item: `raw_request` names the
   item and says it is one of N items bought together for the user's request, `budget_cents` is
   `unit_cap[i]`, plus the item's `must_have` and the shared `must_not`, `preferences` and memories.
   Seeds are `seed + 10 * i`. Items are ranked in parallel with a `ThreadPoolExecutor`.
6. **Guarantee.** An item's options are its ranking, at most 6. If its cheapest candidate is not
   among them, the cheapest candidate takes the last place (replacing the 6th when there are 6).
   Step 3 passed, so the all-cheapest set always fits and step 7 cannot fail.
7. **Pick.** `best_combo` over the options. With no budget, steps 3, 4 and 6 are skipped and every
   item's rank 1 is chosen.
8. **Reasons.** Reason text as in `recommend()`, including the memory sentence. When the chosen
   product is not rank 1, code appends: "Chosen over higher-ranked options to keep the set within $N."
9. **Log** one `recommend_bundle` line: queries, seeds, caps, candidates, rankings and the picked set.

Result: `{"items": [{"name", "quantity", "chosen": {...}, "alternatives": [...]}], "total_cents",
"budget_cents", "budget_note", "note", "rejected", "products"}`. `chosen` and each alternative carry
`id, title, brand, price_cents, url, image, reason, memory_used`. `rejected` entries also carry the
item name. `products` is every product searched, for `session.products`. With no set, `items` is `[]`
and `total_cents` is `None`.

Tests, new file `tests/test_bundle.py` (fake `search_fn`, ranking patched where needed)
- `best_combo`: all rank 1 when affordable; a tight budget moves exactly one item down; a tie on rank
  sum takes the cheaper set; `None` when nothing fits; no budget returns all zeros; 6 items with 6 options each finish quickly.
- Caps: the limit of each item equals the budget minus the other floors, with quantities.
- An infeasible request does not call the ranker (patch it to fail the test if called).
- The guarantee: rankings that only list expensive products still give a set within the budget, and no item has more than 6 options.
- An item with no search result gives no set and names the item.
- `parse_bundle`: 1 item and 7 items are errors; queries are cut to 2; an approximate budget is widened.
- The chosen set's total equals the sum of server prices times quantities.

Docs in the same commit: the F22 entry in `docs/implementation.md`, marked "not yet reachable from the agent".

## 9. Commit 4: F22 in the agent, the keyless mock and the page

`app/agent.py`
- New tool `recommend_bundle`: `raw_request`, `budget_usd`, `budget_is_strict`, `must_not`,
  `preferences`, and `items` (2 to 6 of `{name, queries, quantity, must_have}`).
- `tool_recommend_bundle`: parse, add `session.memory_profile`, run, then
  `session.products.update(...)` and `session.budget_cents = request["budget_cents"]`, exactly as
  `tool_recommend` does. `ui["bundle"]` gets the result for the page. The model gets the chosen
  product per item (id, title, price, reason), the total and the note.
- `SYSTEM_PROMPT`: the first line says "one or more products". New rule: when the user wants several
  different products in one request, call `recommend_bundle` with one entry per product the user
  named; the budget is the total for the whole set; the budget question rule is the same. New rule:
  when the user accepts the set, call `prepare_cart` with `items`.
- Register the tool in `TOOL_FUNCTIONS`. `understand()` stays as it is (the eval has no set requests).

`app/mock_agent.py`
- After removing budget and exclusion phrases, split on commas and "and". Treat the message as a set
  only when there are 2 to 6 parts and every part starts with `a`, `an` or a number ("a tent, 2
  sleeping bags and a backpack"). Otherwise the existing path runs, so "a gift for a coffee and tea
  lover" is still one request. The budget question is asked first, as today.
- `summarize` handles the set result. "buy the set" / "take the set" calls `prepare_cart` with the
  chosen IDs of the last set result.

`app/mock_catalog.json`
- It has only 2 tents and 2 sleeping bags. Add a few products so that at least one demo request has
  3 or more candidates per item and a tight budget visibly moves one item down a rank.

`static/index.html`
- New `showBundle(data)`: one group per item with its name and quantity; the chosen product is
  preselected and the alternatives are radio buttons, each with price and reason; the set total and
  the budget from the server; the note; the ruled-out list as in `showRecommendations`.
- One button, "Review this set", posts the selected IDs and quantities to `/api/cart` and calls
  `showSummary`. When the user changes a selection, the set total line is replaced by "The total is
  recalculated when you review the set". The server refuses a set over the budget and the page shows that message.
- `send()` calls `showBundle` when the response has `bundle`.

Tests
- `tests/test_agent.py`: the tool stores searched products and the total budget on the session; the
  keyless mock turns a three-item message into a `recommend_bundle` call and a single-need message
  into `recommend`; "buy the set" prepares a cart whose total equals the set total; an invented ID in
  `items` is an error.
- `tests/test_api.py`: chat with a set request, review the set, Confirm, mock approve, order
  `COMPLETED` with every item.

Docs in the same commit: finish the F22 entry, update `docs/progress.md` and the README.

## 10. Commit 5: F23 Refund by line

One mechanism for every order: each refund call covers exactly one line and states its amount.
A single-item order is one line, so its refund is one call for the whole amount. This replaces the
empty-body full refund and the request ID `refund-{order_id}`.

Line numbers start at 1 and are the positions in the order's `items` snapshot, as shown to the user.

`app/paypal.py`
- `refund_capture(capture_id, request_id, amount_cents, currency)` sends
  `{"amount": {"value": to_dollars(amount_cents), "currency_code": currency}}`.

`app/paypal_mock.py`
- `refund_capture` takes the body, keeps the refunded total per capture, and refuses a refund that
  would exceed the captured amount with the issue name found in step 0. A repeated request ID still
  returns the stored response.

`app/checkout.py`
- `refund_draft(user_id, order_id, lines=None)`: the order must be this user's and `COMPLETED` or
  `PARTIALLY_REFUNDED`. `lines=None` means every line without a `refund_id`. Refuse an unknown line
  number, a line already refunded, and an empty selection. Return the order ID, the currency, each
  chosen line (number, title, quantity, amount = unit price x quantity) and the sum. Calls nothing.
- `refund(user_id, order_id, lines=None)`, under `LOCK`: repeat the draft checks, then for each line
  in order call `paypal.refund_capture` with `refund-{order_id}-{line}` and that line's amount.
  When the refund status is `COMPLETED`, store the `refund_id` on that item and write the row at
  once: status `REFUNDED` if every line now has a `refund_id`, otherwise `PARTIALLY_REFUNDED`.
  When a call fails or returns another status, stop: lines already refunded stay refunded, the note
  says which line did not go through, and a retry of that line uses the same request ID.
- `MESSAGES` gains `PARTIALLY_REFUNDED`. `order_view` marks each item as refunded or not and adds `refunded_cents`.

`app/store.py`
- `items` must be writable through `update_order` (add it to `UPDATABLE` if it is missing). The
  status comment in the schema gains `PARTIALLY_REFUNDED`. No new column.

`app/agent.py`, `app/main.py`, `app/mock_agent.py`, `static/index.html`
- `draft_refund` gains an optional `lines` array of line numbers. `get_orders` shows each item with
  its line number and whether it was refunded. Prompt rule: a line is refunded only when the order shows it.
- `POST /api/orders/{id}/refund` accepts `{"lines": [..]}`; no body or `null` means all remaining lines.
- The keyless mock reads "refund item 2 of order 5" as line 2 and "refund order 5" as all remaining lines.
- `showRefundDraft` lists the chosen lines and the refund amount from the server and posts the
  draft's lines. `showOrder` marks refunded lines. The Confirm refund button and the "Nothing is
  refunded until you click" note stay.

Tests
- Update the F16 tests for the new request ID and body.
- `tests/test_checkout.py`: one line of a two-line order gives `PARTIALLY_REFUNDED` with that line's
  amount and request ID; the second line gives `REFUNDED`; the same line twice is refused without a
  PayPal call; "all" on a two-line order makes one call per line; a failure on the second line keeps
  the first refunded and a retry reuses the request ID; a single-item order is `REFUNDED` after one
  call for the full amount; another user's order is refused; 4 simultaneous clicks make one call per
  line; refunded line amounts always add up to the order amount.
- `tests/test_paypal.py`: the refund body. `tests/test_api.py`: the endpoint with and without `lines`.
- `tests/test_agent.py`: the model can only draft; the PayPal refund is patched to fail the test if called.

Docs in the same commit: new F23 entry and updated F16 entry in `docs/implementation.md`, the
requirement edits from section 3, `docs/progress.md`, README.

## 11. Verification before calling it done

- `pytest` passes in full after every commit.
- By hand in keyless mode, restarting the server after edits: a three-item set with a comfortable
  budget; the same set with a tight budget (one item moves down and the reason says so); a budget
  below the cheapest set (no set, the price of the cheapest set is shown); swap one item and review;
  Confirm, mock approve, order status; refund one line, then the rest; a single-product purchase and
  its refund still work as before.
- Report honestly what was not verified. Nothing here can be checked against the real model,
  Channel3 or the PayPal sandbox without keys. The line items in the create body and the refund with
  an amount are the two points the first real sandbox payment must confirm; say so in `docs/progress.md`.

## 12. Known limits to write down, not to solve

- The first search only knows the total budget, so a search that returns only expensive products for
  one item can make a set impossible even though cheaper products exist. No second search is made.
- A six-item set makes 18 ranking calls at once. This has not been tried on a real provider.
- The rank sum treats every item as equally important.
- The price is confirmed when the set is reviewed, not again at Confirm (same as F8).
- A refund covers a whole line, not single units. A pending refund is not polled.

## 13. If time runs out

Each commit leaves a working app, so work can stop after any of them:

- After commit 1: multi-item carts, PayPal gets the total only, refunds are for the whole order.
- Commit 2 changes the payment request of every order. Do not start it unless it can be finished and tested.
- Commit 3 alone changes no behaviour. Commit 4 must not be left half done: if it cannot be finished
  and verified, leave it out and list F22 under future work in the README.
- Without commit 5, a set is refunded in full by the existing F16.
