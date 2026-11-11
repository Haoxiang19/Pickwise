# Implementation notes

What was actually built, one entry per feature. Written after each feature is finished.

## M1 Model interface layer (`app/llm.py`, `app/money.py`)

**What it does.** One place that talks to the model through the OpenAI-compatible `/chat/completions` format, plus integer-cent money helpers used everywhere else.

**Where.** `app/llm.py`: `chat`, `ask`, `enabled`, `reset_usage`, module-level `usage`. `app/money.py`: `to_cents`, `to_dollars`.

**How it works.**
1. `chat(messages, tools, temperature, mock)` builds `{"model", "messages", "temperature", "tools"}`, merges the JSON object from `LLM_EXTRA_BODY`, and POSTs to `{LLM_BASE_URL}/chat/completions` with httpx.
2. It returns `choices[0].message` exactly as received, so fields this project does not use (for example `reasoning_content`) survive when the caller appends it to the history.
3. Token counts are added to `usage` from `usage.prompt_tokens` / `usage.completion_tokens`; a missing field counts as 0.
4. Any HTTP error, bad JSON or missing `choices` raises `LLMError`.
5. With no `LLM_API_KEY`, `chat` calls the caller's `mock(messages)` instead. Each caller supplies a rule-based stand-in that returns a message of the same shape, so the rest of the code runs the same path with or without a key.
6. `ask(messages, parse, fallback, ...)` wraps the retry rule: `parse` validates the message and raises `ValueError` on a format error (including a blank reply); one retry, then `fallback` is returned.
7. `to_cents` reads amounts with `Decimal(str(x))` and rejects anything that is not whole cents; `to_dollars` formats cents as `"12.34"`.

**Why.** Plain httpx instead of a provider SDK keeps provider switching to config only and avoids an extra dependency. Putting the mock behind the same `chat` call (instead of `if mock:` branches in every caller) means the agent loop and the ranking parser are exercised by tests even without a key.

**Verified.** `tests/test_llm.py`: mock path, extra body merged, message returned unchanged, missing usage counts 0, HTTP error becomes `LLMError`, retry-once-then-fallback, money conversion.

**Limits / not verified.** No real provider has been called (no key). The `usage` counter is process-wide, so it is only meaningful when requests run one at a time, as in the eval. `LLM_EXTRA_BODY` that is not a JSON object is ignored with a warning.

## M1 Product search and mock catalog (`app/catalog.py`)

**What it does.** Searches Channel3 when `CHANNEL3_API_KEY` is set, otherwise a 53-item local mock catalog, and normalizes every result to the Product shape from requirements section 7.

**Where.** `app/catalog.py`: `search`, `normalize`, `_channel3_search`, `_mock_search`. Data: `app/mock_catalog.json` (stored in Channel3's raw shape).

**How it works.**
1. `search(query, limit=10)` gets raw results from Channel3 (`POST /v1/search` with `{"query", "limit", "config": {"currency": "USD"}}` and the `x-api-key` header) or from the mock, then calls `normalize` on each.
2. Mock search: lowercase word sets with stopwords removed and a crude plural fold; score = 2 x shared words with the title + shared words with description/category/brand; top `limit` by score, catalog order on ties.
3. `normalize` keeps only USD offers with a parseable price (`price.price`, falling back to `price.amount`; read with `Decimal`), picks the cheapest in-stock one. An offer counts as in stock unless its availability is `OutOfStock`, `SoldOut`, `PreOrder` or `BackOrder`, because Channel3 treats a missing value as in stock; an unknown value is logged once. If none is in stock it keeps the cheapest USD offer with `in_stock=False`; with no USD offer at all, `price_cents` and `currency` are `None`. These two cases map to the "out of stock" and "no in-stock USD offer" rejection reasons in F4.
4. Main image is the one with `is_main_image`, else the first; brand is `brands[0].name`; category is `category.title`.
5. Channel3 failures raise `CatalogError`, whose message carries Channel3's `error.code`. A 429 or 5xx is retried once, waiting `Retry-After` (capped at 10 seconds); network errors and 4xx are not retried.

**Why.** Keeping the mock in Channel3's raw shape means the same `normalize` code runs in tests and keyless mode, so the mapping is exercised even without a key. The budget is not sent as a Channel3 filter, so over-budget items can be shown as rejected.

**Verified.** `tests/test_catalog.py`: cheapest in-stock USD offer chosen, out-of-stock and non-USD cases, missing fields, mock search, Channel3 request shape (with a fake HTTP call).

**Limits / not verified.** No real Channel3 call yet. The dollar unit of the price comes from the docs only; a unit mistake would be a 100x price error and must be checked against a real response. The docs contradict themselves on the price field name and list more availability values than the schema accepts, so both are handled defensively (see `docs/decisions.md`). Variants (size, colour) are ignored, and prices are not refreshed between the search and the cart. The mock search is word overlap only.

## F3 Multi-query search, F4 Hard-constraint filter (`app/recommend.py`)

**What it does.** Runs each search query from the structured request, merges the results, and removes products that break a hard constraint, recording why.

**Where.** `app/recommend.py`: `parse_request`, `search_all`, `rejection`, `round_robin`, `hard_filter`.

**How it works.**
1. `parse_request(args)` cleans the model's tool arguments: `budget_usd` becomes `budget_cents` through `to_cents` (`None` means no limit), empty strings are dropped, at most 4 queries are kept, and if there are none the raw request is the only query. An empty `raw_request` raises `ValueError`.
2. `search_all(queries, search_fn, max_price_cents)` calls `catalog.search(q, 10, cap)` per query and merges by product ID with `dict.setdefault`, so a product returned by several queries keeps the first query's index (`query_index`).
2a. The cap is sent whenever the version has `budget_filter` on and the request has a budget. It becomes Channel3's `filters.price.max_price`, which keeps the ten results per query full of products the user can afford. It is an optimisation: `rejection()` still checks the budget, so an ignored or wrong cap cannot produce an unaffordable recommendation.
2c. `budget_from(args)` turns the model's `budget_usd` and `budget_is_strict` into the limit: a firm budget is taken as given, an approximate one ("around $70") is widened by `APPROXIMATE_MARGIN` (20%) and rounded up to a whole dollar, giving $84. That one figure is `budget_cents`, which the cap, the hard filter and the cart check all use; `budget_stated_cents` keeps the original only so `budget_note` can explain the difference to the user.
2b. With the cap on, `over_budget_examples` runs one extra search on the raw request without the cap and keeps only the over-budget products, so F6 can still show what the budget ruled out. They never become candidates.
3. `rejection(p, budget_cents, must_not)` checks in order: no USD offer, out of stock, price above budget (skipped when the budget is `None`), and must-not keywords. Keywords match title and brand only, case-insensitive, whole word (`\b...\b`). It returns a `(kind, reason)` pair; `kind` is used later to count reasons.
4. `hard_filter` splits products into passing and rejected (with ID, title, price, kind, reason), interleaves the passing ones round-robin by source query, and keeps the first 20.

**Why.** Constraints are enforced in code, not in the prompt, so a model mistake cannot recommend an over-budget item. The model's only say in the budget is how it was phrased; the margin that follows from it is a constant in the code, so the limit stays a fixed function of what the user said (see `docs/decisions.md`). Round-robin before the 20-item cap stops the first query from filling every slot. The description is not checked for must-not words because phrases like "not leather" would cause false matches (requirements section 4).

**Verified.** `tests/test_recommend.py`: budget conversion and list cleaning, merge keeps first query, each rejection reason, budget equal passes, no-budget skips the check, whole-word and brand matching, description ignored, round-robin order and the 20 cap; for the cap: a pool of unaffordable results becomes affordable, the ruled-out list still fills from the extra search, a catalog that ignores the cap changes nothing, and no budget means no cap and no extra search; for the margin: a firm budget is unchanged, an approximate one is widened by 20% and rounded up, and the widened figure is the only limit used by the cap, the filter and the reply. `tests/test_agent.py`: an approximate budget reaches the cart check too, so a product the strict reading would have refused can be ordered. Run by hand on the mock catalog: 3 queries, 15 products found, 9 passed, 6 rejected with the expected reasons.

**Limits.** Whole-word matching uses regex `\b`, so a keyword like "c++" would not match as expected. Search errors (`CatalogError`) are not caught here; the agent tool layer returns them to the model.

## F5 Reasoning rank, F6 Show recommendations (`app/recommend.py`)

**What it does.** Asks the model to reason about the shuffled candidates and then rank them by ID, validates the ranking, picks 3 with a one-sentence reason each, and returns them together with the rejected products and a note when fewer than 3 passed.

**Where.** `app/recommend.py`: `rank`, `parse_ranking`, `pick_top3`, `recommend`, `RANK_PROMPT`. Display is in the page (built with the agent, F1/F2 commit).

**How it works.**
1. `rank(request, candidates, seed)` copies the candidates and shuffles them with `random.Random(seed)`.
2. Each candidate is sent as one JSON line with only ID, title, price, brand and the first 200 characters of the description. The system prompt says product text is untrusted and its instructions and claims must be ignored.
3. The model writes a short analysis, then one line `{"ranking": [{"id", "reason"}]}`.
4. `parse_ranking` reads the last `{"ranking"` JSON with `raw_decode`, drops unknown and repeated IDs, keeps at most 6, and raises `ValueError` on a blank reply, bad JSON or no valid ID. `llm.ask` retries once, then falls back to search order.
5. `pick_top3`: with 3 or more queries, walk the ranking taking at most one product per source query; fill the remaining places in rank order, then in search order if fewer than 3 were ranked.
6. `recommend(request, flags, search_fn, seed)` runs search, filter, rank (skipped when `reasoning_rank` is off, which means search order; with `rank_shuffles` > 1 it is the F17 multi-shuffle rank), pick, and builds each recommendation (ID, title, brand, price in cents, URL, image, reason; a default reason names the source query). If fewer than 3 remain, `note` says how many were removed, grouped by reason, and suggests a change. One log line records queries, seed, candidates, rejections, ranking and picks.
7. Keyless mode: the mock reply is search order in the same JSON format, so `parse_ranking` still runs.

**Why.** Reasoning before ranking follows BracketRank (appendix A); shuffling removes the search order as a hint and the logged seed makes a run repeatable. Validation choices are in `docs/decisions.md` (F5). `search_fn` and `seed` are parameters so the eval can replay a snapshot.

**Verified.** `tests/test_recommend.py`: parsing after reasoning text, unknown and duplicate IDs, last JSON wins, cap at 6, six format-error cases, pick rules (one per query, fill, search-order fill), mock rank, fallback on a bad reply, prompt contains the untrusted-data rule and no URL or long description, same seed gives the same shuffle, end-to-end in mock mode, fewer-than-3 note. Run by hand in mock mode: "a gift for a coffee lover under 60" gives 3 products, 5 rejected.

**Limits / not verified.** Not run against a real model, so ranking quality and how often the JSON line is malformed are unknown. Prices in the prompt are formatted by the server; the model's output never carries prices.

## F1 Parse the request, F2 Ask when the budget is missing (`app/agent.py`, `app/mock_agent.py`, `app/main.py`)

**What it does.** A hand-written tool loop turns the user's message into a structured request (budget, must-have, must-not, preferences, 3-4 queries) by having the model call the `recommend` tool, or into one budget question when no budget was given.

**Where.** `app/agent.py`: `SYSTEM_PROMPT`, `TOOLS`, `tool_recommend`, `run_tool_call`, `check_reply`, `handle_message`. `app/mock_agent.py`: `reply`, `parse_budget`, `build_request`, `summarize`. `app/store.py`: `Session`, `get_session`. `app/main.py`: cookie middleware, `POST /api/chat`, `GET /api/status`. `static/index.html`: chat, cards, "Ruled out" list, mock badges.

**How it works.**
1. `POST /api/chat` finds the session by the `uid` cookie (random, `HttpOnly`, `SameSite=Lax`, set by the middleware) and calls `handle_message`.
2. The user message is appended to the session history. Each round sends the system prompt plus history and the tool list through `llm.ask` with `check_reply` (a reply must have tool calls or non-blank text; one retry, then a fixed fallback reply).
3. The assistant message is appended unchanged. Without tool calls its text is the reply. Otherwise every call is run by `run_tool_call` and answered with a `tool` message; unknown tools, bad JSON arguments and any exception become `{"error": ...}` for the model.
4. After 5 tool rounds the loop appends and returns a fixed reply, so the history stays valid.
5. `tool_recommend` runs `parse_request` and `recommend`, stores every searched product in `session.products` (the only IDs that may later enter a cart) and the budget in `session.budget_cents`, puts the cards and rejections into the page data, and gives the model a compact result (ID, title, formatted price, reason, rejected count, note).
6. F2 is a prompt rule: ask one budget question when none is given; with "no limit", call `recommend` without `budget_usd` (budget `None`, budget checks skipped).
7. Keyless mode: `mock_agent.reply` uses regexes for the budget (`$100`, `100 dollars`, `under 100`, a bare number after the question, "no limit") and for exclusions (`no X`, `without X`), splits the rest on "and"/commas into queries, and returns a real `tool_calls` message. After a tool result it writes a one-line summary.

**Why.** No agent framework, so every step of the loop can be explained. The loop follows the Chat Completions pattern in the DeepSeek guide; limits and error handling are compared in `docs/decisions.md` (F1, F2). The model gets formatted prices for its reply, but cards use server prices in cents.

**Verified.** `tests/test_agent.py`: asks once without a budget and does not search; the budget answer combines with the earlier request; budget in the first message searches directly; "no limit" skips budget checks; message appended unchanged (extra field kept) and the tool message follows; unknown tool and bad arguments returned to the model; 5-round limit; blank reply retry and fallback; no money tools. `tests/test_api.py`: cookie flags, chat flow, per-user sessions. By hand in the browser (keyless): "I need running shoes, no Nike" then "$120" gave the budget question, then 2 cards, the note, and 4 ruled-out products with reasons.

**Limits / not verified.** Function calling has not been run on a real model (no key), so whether DeepSeek follows the ask-once rule and writes good queries is unknown until the eval. The mock understands only simple phrasings. Sessions are in memory and lost on restart; concurrent messages in one session are not serialized.

## F8 Order summary (`app/store.py`, `app/agent.py`, `app/main.py`)

**What it does.** Turns a chosen product into a cart (a 15-minute price quote) whose items and total are computed by the server in integer cents, and shows it as an order summary.

Since F21 the same checks run per line in `create_cart_items`, and `create_cart` is a one-line wrapper around it (see the F21 entry).

**Where.** `app/store.py`: `create_cart`, `_refreshed`, `get_valid_cart`, `CartError`, `Session.carts`. `app/catalog.py`: `get_product`. `app/agent.py`: `prepare_cart` tool (`tool_prepare_cart`), `cart_view`. `app/main.py`: `POST /api/cart` (the card's Choose button). `static/index.html`: `showSummary`.

**How it works.**
1. The model calls `prepare_cart(product_id, quantity)`, or the user clicks Choose on a card, which posts the same two fields.
2. `create_cart` looks the ID up in `session.products` (only products returned by a search in this session); unknown IDs are refused.
3. The product is then read back from the catalog with the free `catalog.get_product`, because a search result can be minutes old and Channel3 asks for prices and availability to be refreshed before they are shown. The session's copy is replaced by the fresh one. A product that no longer exists, or a catalog failure, refuses the cart rather than quoting an unconfirmed price.
4. It refuses products that are out of stock, have no price or are not USD, and quantities outside 1-10. These checks run on the refreshed product, so an item that just sold out is caught here.
5. Total = server unit price x quantity, in cents. When the refreshed price differs from the one the card showed, that cart item carries `price_was_cents` and both the page and the agent say so. If the session has a budget and the total is above it, the cart is refused; with no budget the check is skipped.
6. The cart gets a random ID, an item snapshot (product ID, title, brand, unit price, quantity), the total, `USD`, and `expires_at` = now + 15 minutes. `get_valid_cart` (used by Confirm in F9) refuses unknown or expired carts.
7. Rule errors are `CartError`, shown to the user (HTTP 400) or returned to the model as a tool error.
8. The page shows product, unit price, quantity and total from the server's response, plus the price-change line when there is one.

**Why.** The model only names a product ID, so it cannot set a price; any price field in its arguments is ignored. Carts are per session, so one user cannot order with another user's search results. The cart is only a quote: Confirm (F9) copies it to the order row, which then becomes the reference. The read-back before quoting mirrors the read-back before capture in F11; both are in `docs/decisions.md`.

**Verified.** `tests/test_store.py`: integer-cent total, unknown ID, quantity bounds and type, unavailable products, budget on the total, no-budget skip, expiry at 15 minutes, and for the read-back: the refreshed price is used and recorded as a change, an unchanged price is not reported, a product that sold out or rose over budget is refused, a product that disappeared is refused, a catalog failure refuses the cart instead of quoting a stale price, and the default path calls `catalog.get_product`. `tests/test_catalog.py`: `get_product` from the mock catalog and over HTTP (URL shape, both response envelopes, 404 means gone, retry, error code). `tests/test_agent.py`: "take the second one" prepares the right cart at the server price; a model-supplied price is ignored; an invented ID returns an error. `tests/test_api.py`: Choose endpoint works, and another browser cannot use this session's product. By hand (keyless): "a yoga mat under $120", Choose on the second card shows Lululemon The Mat 5mm, $108.00, quantity 1, total $108.00.

**Limits.** Expired carts stay in memory until restart. The quantity can only be changed by asking the agent; the page always sends 1. The read-back costs one free Channel3 call per Choose click and has not been run against the real API, so the response envelope of `GET /v1/products/{id}` is handled defensively; the price is confirmed at Choose but not again at Confirm, so a change during the 15-minute quote is not caught.

## F9 User confirmation, F10 Create order and redirect (`app/checkout.py`, `app/paypal.py`, `app/paypal_mock.py`, `app/store.py`)

**What it does.** Only the Confirm click creates a payment: it copies the cart onto an order row (`CREATED`), creates a PayPal Orders v2 order for exactly that amount, and redirects the browser to PayPal's approval page.

**Where.** `app/checkout.py`: `confirm`, `LOCK`, `CheckoutError`, `order_view`, `MESSAGES`. `app/paypal.py`: `BASE_URL`, `_access_token`, `_call`, `create_order` (plus `get_order`, `capture_order`, `refund_capture` used later). `app/paypal_mock.py`: in-memory PayPal. `app/store.py`: `orders` table, `create_order`, `get_order`, `get_order_by_cart`, `list_orders`, `update_order`. `app/main.py`: `POST /api/confirm`, `GET /mock-paypal/checkout`, `POST /mock-paypal/approve`. Page: Confirm button in the summary.

**How it works.**
1. The page posts the cart ID to `/api/confirm`; the button disables itself after the first click.
2. Under `checkout.LOCK`, `confirm` looks for an order row with this `cart_id` and user. If none, it checks the cart is this session's and not expired (the 15-minute quote ends here) and inserts a row: user, cart ID, amount, currency, JSON item snapshot, status `CREATED`. `cart_id` is `UNIQUE`.
3. A row that is no longer `CREATED` is refused ("choose the product again"). A row that already has an approval link is returned as is, so a second Confirm gives the same order and link.
4. Otherwise `paypal.create_order` receives the row's amount and its `items` snapshot. It first checks in code that the items (unit price x quantity) add up to the amount and raises `ITEM_TOTAL_MISMATCH` without sending anything if not (F21). It sends `intent: CAPTURE`; the amount as a string from cents (`to_dollars`) with `breakdown.item_total` equal to it, since there is no tax or shipping; one entry in `purchase_units[0].items` per product (`name` = title cut to PayPal's 127-character limit, `quantity` as a string, `unit_amount` from cents); and `payment_source.paypal.experience_context` with `return_url`/`cancel_url` carrying our local order ID, `PAY_NOW` and `NO_SHIPPING`, with `PayPal-Request-Id: create-{cart_id}`. It returns the order ID and the `payer-action` link, which are stored on the row.
5. If PayPal fails, the row stays `CREATED` without a link and the user sees "Nothing was charged"; clicking again retries with the same request ID.
6. `paypal._call` adds the cached bearer token (client-credentials, reused until a minute before `expires_in`) and the request ID, turns 5xx and network failures into issue `NETWORK_ERROR`, and other errors into `details[0].issue` or `name`.
7. Without PayPal credentials, `paypal_mock` returns responses of the same shape, keeps request-ID idempotency, applies the item-sum rules from the Orders v2 docs (`ITEM_TOTAL_REQUIRED`, `ITEM_TOTAL_MISMATCH`, `AMOUNT_MISMATCH`, in `_check_item_totals`) so a wrong body fails in tests, and `/mock-paypal/checkout` shows a clearly labelled page with Approve and Cancel.

**Why.** Redirect flow so the page needs no PayPal JavaScript. Local row first, then PayPal, so a retry can always find the row; see `docs/decisions.md` (F9-F14) for the sources compared. `BASE_URL` is a constant so the app can never reach live PayPal.

**Verified.** `tests/test_checkout.py`: row and PayPal order created with the right amount, URLs and request ID; second Confirm returns the same order; expired and foreign carts refused; PayPal failure keeps the row and retries with the same request ID; non-`CREATED` row refused; orders private per user; a two-item cart's row items are what Confirm passes to `create_order`. `tests/test_paypal.py` (fake HTTP): sandbox base URL constant, create body and headers (amount with `item_total`), the body for a two-item order with string quantities, a 300-character title cut to 127, a sum mismatch or empty item list sends nothing, the mock raises each of the three sum issues, `payer-action` link, token cached, capture/refund empty body and request IDs, error issue parsing, missing link. By hand (keyless): request, "take the first one", Confirm, landed on the mock PayPal page showing "Pay 59.99 USD". After the line-item change (server restarted): a one-item order ($108.00) and a two-item order (2 x $59.99 + $348.00 = $467.98) both passed the mock's sum checks, were approved, ended `COMPLETED` and were refunded.

**Limits / not verified.** No real sandbox call yet: the `payer-action` link, `PAYER_ACTION_REQUIRED` status and token response are from the docs only. The line items and `item_total` follow the Orders v2 schema (see `docs/decisions.md`, F21-F23) but have never been accepted by the real sandbox; the first real payment must confirm them. Item names are cut by Python character count, which matches PayPal's limit for ordinary text but was not checked for emoji or other characters outside the Basic Multilingual Plane. `APP_BASE_URL` must be set on Render so the return URL uses the public host.

## F11 Verify, then capture; F13 Cancel and failure messages; F14 Success page (`app/checkout.py`, `app/main.py`)

**What it does.** When the buyer returns from PayPal, the server reads the order back, captures only if it is `APPROVED` with the same amount and currency as the order row, and records the result; cancel and every failure say nothing was charged; the page shows the stored result and order ID.

**Where.** `app/checkout.py`: `handle_return`, `handle_cancel`, `_record_capture`, `_fail`, `_keep_for_retry`, `MESSAGES`, `order_view`, `CAPTURE_WINDOW_SECONDS`. `app/main.py`: `GET /paypal/return`, `GET /paypal/cancel`, `GET /api/orders/{id}`. `static/index.html`: `showOrder`.

**How it works.**
1. PayPal redirects to `/paypal/return?order_id=<local id>` (PayPal's own `token`/`PayerID` parameters are ignored). The row is loaded by local ID **and** the cookie's user; another user gets 404.
2. Under `checkout.LOCK`: a row that is not `CREATED` (or has no PayPal ID) is returned unchanged, so a refresh never calls PayPal again.
3. Older than 3 hours: `CAPTURE_FAILED` without calling PayPal.
4. `GET` the PayPal order using the ID stored on the row. If it is already `COMPLETED`, the capture inside it is recorded. If it is not `APPROVED`: `CANCELLED`.
5. Amount check: `to_cents(purchase_units[0].amount.value)` (Decimal) and `currency_code` must equal the row; otherwise `AMOUNT_MISMATCH` and no capture.
6. Capture with `PayPal-Request-Id: capture-{order_id}`. Paid (`COMPLETED`, `capture_id` stored) only if `purchase_units[0].payments.captures[0].status == "COMPLETED"`; any other capture status is `CAPTURE_FAILED`.
7. Capture errors: `ORDER_ALREADY_CAPTURED` reads the order back and records its real state; `ORDER_NOT_APPROVED` is `CANCELLED`; `INSTRUMENT_DECLINED` and anything else are `CAPTURE_FAILED` with a note. No response (network error or 5xx) keeps the row `CREATED` with a note, and the page shows "Check again", which revisits the return URL with the same request ID.
8. `/paypal/cancel` marks a `CREATED` row `CANCELLED`; other states are left alone.
9. Both endpoints redirect (303) to `/?order_id=<id>`; the page calls `GET /api/orders/{id}` and shows the message, items, total, PayPal order ID and status. Refreshing that page only reads.

**Why.** The read-back check is this project's addition to PayPal's sample flow (see `docs/decisions.md`, F9-F14). The redirect after capture separates the action URL from the result URL. Keeping an unanswered capture as `CREATED` instead of `CAPTURE_FAILED` avoids telling a buyer "nothing was charged" when PayPal may have captured (listed as a question in `docs/progress.md`).

**Verified.** `tests/test_checkout.py`: capture after approval with the right request ID; refresh does not call PayPal; not approved means cancelled without capture; four amount/currency mismatch cases; error mapping for declined, not approved and unknown issues; `PENDING` capture is not paid; already-captured reads back; `COMPLETED` on read-back recorded without capture; network error then retry succeeds; 3-hour window; cancel only from `CREATED`; another user cannot return or cancel. `tests/test_api.py`: full mock purchase (a forged PayPal ID in the return URL is ignored) and cancel flow with privacy. By hand (keyless): French press, Confirm, Approve, result "Payment successful. Order #2, $39.95, PayPal order ID MOCK-..., COMPLETED"; water bottle request, Confirm, Cancel, result "Payment cancelled. Nothing was charged."

**Limits / not verified.** Not run against the sandbox: that an approved order reads back as `APPROVED`, the real error body shape, and other capture statuses are from the docs. A `PENDING` capture is shown as failed with "Nothing was charged", which may be wrong for a real pending capture (question in `docs/progress.md`). If the server restarts, orders are lost (Render free tier).

## F12 No double charge (`app/checkout.py`, `app/store.py`, `static/index.html`)

**What it does.** Repeated clicks, simultaneous requests and page refreshes never create a second PayPal order or a second capture.

**Where.** `checkout.LOCK`; the status checks at the top of `confirm` and `handle_return`; `UNIQUE` on `orders.cart_id`; deterministic request IDs in `confirm` / `handle_return`; the Confirm button's `disabled` flag; the 303 redirect to the read-only result page.

**How it works (four layers, from the outside in).**
1. Page: the Confirm button disables itself on the first click.
2. Result page: after capture the browser is redirected to `/?order_id=...`, which only reads the order. Refreshing it never captures.
3. Local state, under one process-wide lock: Confirm reuses the row for a cart (and its stored approval link); capture runs only from `CREATED`; refund (F16) only from `COMPLETED`. The lock makes "check status, then call PayPal, then write status" one step for concurrent requests.
4. PayPal: `create-{cart_id}`, `capture-{order_id}` and `refund-{order_id}` as `PayPal-Request-Id`, so a retry returns PayPal's earlier result instead of repeating the action.

**Why.** The request ID alone is not enough: PayPal does not document how long it keeps order request IDs, and it may reject two simultaneous requests with the same ID. A lock is enough because the app runs as one worker process (requirements section 10); several workers would need a database-level guard instead.

**Verified.** `tests/test_double_charge.py`: 5 threads confirming the same cart make one PayPal create call and one order; 5 threads returning from PayPal make one capture call; the same capture request ID gives the same capture in the mock; a new cart after a cancel gets a new order. Both thread tests fail when the lock is replaced by a no-op (checked by hand). Also covered: `test_second_confirm_returns_same_order_and_link`, `test_refresh_after_result_does_not_call_paypal`.

**Limits / not verified.** The lock does not protect across processes or restarts. PayPal's real behaviour for repeated request IDs was not observed (no sandbox credentials).

## F7 Refine from feedback (`app/agent.py`, `app/mock_agent.py`)

**What it does.** After a follow-up such as "cheaper", "a different brand" or "also no Osprey", the agent recommends again under the new condition while keeping the earlier ones.

**Where.** `app/agent.py`: refine rule in `SYSTEM_PROMPT`; `tool_recommend` now also gives the model each product's brand. `app/mock_agent.py`: `last_recommend_args`, `refine`, `CHEAPER`, `OTHER_BRAND`, `FOLLOW_UP`.

**How it works.**
1. Real model: the whole history (including the earlier `recommend` call and its result) is sent every turn, and the prompt says to call `recommend` again with the full updated request, keeping every earlier condition unless the user changed it. Each `recommend` call carries the complete request, so nothing depends on hidden state.
2. The new call goes through the same pipeline: search, hard filter (new budget and exclusions enforced in code), rank, pick. `session.budget_cents` is replaced by the new request's budget, so the cart check uses it.
3. Keyless mock: if a previous `recommend` call exists and the message says "cheaper", names "different/another/other brand", or starts with "but/also/and/actually/only/now", `refine` copies the earlier arguments and changes only what the message adds: a stated budget; or "cheaper" = 80% of the earlier budget (whole dollars), or of the highest shown price if there was no budget; "no limit" removes the budget; new `no X` words and, for "different brand", the brands just shown are added to `must_not`.

**Why.** Keeping the conditions in the model's structured tool call (rather than merging them in code) lets the user also remove a condition ("Nike is fine now"); code still enforces whatever the current call says. The mock's 80% rule is only a stand-in so the keyless demo can show the behaviour.

**Verified.** `tests/test_agent.py`: "cheaper" lowers the budget to $80 and keeps the JBL exclusion and queries; "different brand" excludes all shown brands and keeps the budget; "also no Osprey" adds to "no leather"; prompt contains the rule. By hand (keyless): "running shoes under $150, no Nike" then "something cheaper" gave products at or below $120 with Nike still excluded and the fewer-than-3 note.

**Limits / not verified.** Whether a real model keeps earlier conditions reliably is not measured (multi-turn eval is P2). The mock only recognises the phrasings listed above.

## F15 Order status (`app/agent.py`, `app/store.py`)

**What it does.** When the user asks about an order, the agent returns the order ID, status and amount from the database, only for this user's orders.

**Where.** `app/agent.py`: `get_orders` tool (`tool_get_orders`), prompt rule. `app/store.py`: `Session.user_id`, `get_order`, `list_orders`. `app/mock_agent.py`: `ORDER_QUESTION`, `ORDER_ID`. Page: each order is shown with `showOrder`.

**How it works.**
1. The model calls `get_orders` with an optional `order_id` (read-only tool tier).
2. With an ID: `store.get_order(id, session.user_id)`; without: the latest 5 orders of this user. The SQL always filters by `user_id`, so another user's order is "not found".
3. Each row goes through `checkout.order_view` (ID, status, amount, items, PayPal order ID, status message). The model gets ID, status, formatted amount and item titles; the page gets the full views.
4. Keyless mock: "order status", "my orders", "order #3" and similar call the tool, then list `#id STATUS $amount`.

**Why.** The session stores the cookie's user ID so tools can filter by owner without the model ever supplying a user ID.

**Verified.** `tests/test_agent.py`: after a mock purchase, "status of order #N" returns that order as `COMPLETED` with the right amount; "show my orders" lists it; another user gets nothing. By hand (keyless, after a server restart with the same cookie): "what is my order status?" listed #3 CANCELLED $27.99, #2 COMPLETED $39.95, #1 CREATED $59.99.

**Limits.** Orders live in SQLite on the server's disk, which Render's free tier does not keep across restarts. After a restart the mock PayPal forgets its orders, so "Check again" on an old `CREATED` order only shows "Could not reach PayPal".

## F16 Refund (`app/checkout.py`, `app/agent.py`, `app/main.py`)

**What it does.** The agent can only draft a full refund; PayPal is called only after the user clicks Confirm refund, and an order that was refunded cannot be refunded again.

**Where.** `app/checkout.py`: `refund_draft`, `refund`. `app/agent.py`: `draft_refund` tool (`tool_draft_refund`), prompt rule. `app/main.py`: `POST /api/orders/{id}/refund`. `app/mock_agent.py`: `REFUND`. Page: `showRefundDraft`.

**How it works.**
1. The model calls `draft_refund(order_id)`. `refund_draft` checks the order belongs to this user, is not `REFUNDED`, and is `COMPLETED`; it returns order ID, amount, currency and items. Nothing is sent to PayPal. Errors go back to the model as tool errors.
2. The page shows the draft with "Nothing is refunded until you click Confirm refund" and a Confirm refund button that disables itself on click.
3. The button posts to `/api/orders/{id}/refund`. Under `checkout.LOCK`, `refund` repeats the same checks (local status first), then calls `paypal.refund_capture(capture_id, "refund-{order_id}")` with an empty body (full refund).
4. Refund status `COMPLETED`: the row becomes `REFUNDED` and stores `refund_id`. Any other status (e.g. `PENDING`): the row stays `COMPLETED` with a note, and a retry uses the same request ID. A PayPal error leaves the row unchanged and tells the user they can try again.
5. A second refund is refused locally ("already refunded") without calling PayPal.

**Why.** Refund is in the money tier, so the model only proposes it (requirements section 6). The capture ID comes from our row, saved at capture time.

**Verified.** `tests/test_checkout.py`: draft then refund marks `REFUNDED` with the right request ID; second refund and second draft refused without calling PayPal; unpaid and foreign orders refused; PayPal error and `PENDING` leave the order `COMPLETED`; 4 simultaneous clicks make one PayPal call. `tests/test_agent.py`: "I want a refund for order N" only drafts (PayPal refund patched to fail the test if called), and there is no refund tool. `tests/test_api.py`: refund endpoint after a mock purchase, other user refused, second refund refused. By hand (keyless): bought a chef's knife ($54.00, order #4), "please refund order 4" showed the draft, Confirm refund showed "This order was refunded", status `REFUNDED`.

**Limits / not verified.** No sandbox refund was made. Partial refunds are not supported. A pending refund is not polled; the user has to retry.

## M4 Eval script (`eval/`)

**What it does.** One command builds or loads a search snapshot, measures ask accuracy live, replays the snapshot through three ablation versions, and prints constraint satisfaction, grounding, over-budget count, injection resistance, NDCG@3, latency and cost per version and request type.

**Where.** `eval/run_eval.py`: `build_snapshot`, `load_snapshot`, `ask_accuracy`, `run_one`, `summarize`, `to_label`, `main`. `eval/metrics.py`: `ndcg_at_3`, `meets_constraints`, `is_over_budget`, `is_grounded`, `mean`. Data: `eval/requests.json`, `eval/adversarial.json`, `eval/labels.json` (empty). App hooks: `agent.understand` (step 1 alone, same prompt and tools as the agent), `recommend(..., inject=...)` and the `ranking` field in its result, `llm.DEFAULT_TEMPERATURE`.

**How it works.**
1. Snapshot: on the first run, for each clear, gift, adversarial and preference request, `agent.understand` produces the structured request, then every query and the raw request text are searched (10 results each). Saved as `snapshot.json` only when both the model and Channel3 are real, otherwise `snapshot_mock.json`. Existing entries are never rewritten; a test request added later gets its own dated entry (added with F19).
2. Ask accuracy: `agent.understand` on all 31 requests; correct when it asked exactly for the 5 missing-budget requests.
3. Replay: for each version (baseline: one search with the raw words, search order; + multi-query; + reasoning rank; + multi-shuffle with 3 shuffles; + budget filter; + memory) and each seed, `recommend` gets a `search_fn` that reads the snapshot. Hostile listings are injected in front of the results; the runner raises if one would fail the hard filter.
4. Per request it logs queries, candidates, rejection reasons, ranking, recommendations, and computes: constraint check per product (F4 rule), grounding against the snapshot results (not the pipeline's own copy), over-budget count, hostile IDs in the top 3, seconds, model calls and tokens.
5. `summarize` computes each metric per run, then averages over runs. NDCG@3 is averaged over requests whose top 3 are fully labelled; the rest are counted as unlabeled. `to_label.json` lists every recommended product without a label (pooling).

**Why.** Replaying a fixed snapshot gives every version the same products, and replaying step 1 avoids new model-written queries that would not be in the snapshot. Metric choices and the NDCG definition are compared in `docs/decisions.md` (M4).

**Verified.** `tests/test_eval.py`: NDCG perfect, reversed, ideal from all labels, unlabeled is incomplete, all-zero is 0; constraint, budget and grounding helpers; 27 requests with the right type counts; 3 hostile kinds per adversarial request; labels file empty; `run_one` and `summarize` on a tiny snapshot; a hostile listing that would be filtered is refused. By hand: `python -m eval.run_eval --name mock-check` in keyless mode ran all versions, printed the table with the mock warning, and wrote logs and `to_label.json` (22 requests to label). Those mock numbers are not results and are not reported anywhere.

**Limits / not verified.** No real snapshot exists yet (needs LLM and Channel3 keys), so there are no eval numbers. Labels are empty. P1 rows (multi-shuffle, memory) and the preference requests are not built. Hostile listings are placed first, so injection resistance for search-order versions only reflects placement.

## F17 Multi-shuffle ranking (`app/recommend.py`, `app/llm.py`, `eval/run_eval.py`)

**What it does.** Ranks 3 differently shuffled copies of the candidates in parallel and combines the 3 rankings by mean rank, which reduces the effect of input order on the ranker.

**Where.** `app/recommend.py`: `rank_shuffled`, `aggregate`, `MISSING_RANK`, `DEFAULT_FLAGS["rank_shuffles"]`. `app/llm.py`: `_usage_lock`. `eval/run_eval.py`: version "+ multi-shuffle".

**How it works.**
1. `recommend` reads `flags["rank_shuffles"]` (app default 3; the eval sets it per version). With 1, `rank_shuffled` just calls the F5 `rank`.
2. Otherwise it calls `rank(request, candidates, s)` for s = seed, seed+1, seed+2 in a `ThreadPoolExecutor`; each call shuffles with its own seed and is validated, retried and given a fallback exactly as in F5.
3. `aggregate` collects every product ID any ranking listed, in order of first appearance. For each ranking a product gets its position (1-6), or 7 if that ranking did not list it. Products are sorted by mean position; `sorted` is stable, so ties keep first-appearance order. At most 6 are kept.
4. Each product keeps the reason from the ranking where it placed highest (the first non-empty one in position order).
5. `pick_top3` then works as before. The log line records the number of shuffles; the seeds follow from the logged seed.
6. Token counting is protected by a lock, because the three calls update `llm.usage` from different threads.

**Why.** Mean rank (Borda-style) instead of Kemeny-Young, which the Permutation Self-Consistency paper uses: much simpler to explain, and with 3 lists of at most 6 items the difference is small. See `docs/decisions.md` (F17). Threads because the calls only wait on the network.

**Verified.** `tests/test_multi_shuffle.py`: mean rank with missing = 7 on a worked example, ties keep first appearance, cap at 6, reason from best placement, single ranking unchanged, 3 calls with the same shuffles as seeds 10, 11, 12 in F5, 1 shuffle equals plain `rank`, `recommend` makes 3 model calls in mock mode. By hand: `python -m eval.run_eval --name mock-f17 --runs 1` (keyless) prints the "+ multi-shuffle" rows with 3 calls per request (mock numbers, not results).

**Limits / not verified.** With a real model this triples ranking cost; latency should stay close to one call because the calls run in parallel, but that is not measured. A ranking that failed twice falls back to search order and still counts as one of the 3 rankings, which pulls the result toward search order. In mock mode all three rankings are identical.

## F18 Preference memory: write (`app/memory.py`, `app/agent.py`, `app/checkout.py`)

**What it does.** Saves a one-sentence preference per user with a strength in [-1, 1] when the user states a lasting preference, rejects a recommendation with a reason, or completes a purchase; repeating a preference adds 0.1, contradicting it subtracts 0.2.

**Where.** `app/memory.py`: `preferences` table, `remember`, `_adjust`, `record_purchase`, `list_preferences`, `prompt_block`. `app/agent.py`: `remember_preference` tool (`tool_remember_preference`), `system_prompt`, prompt rules. `app/checkout.py`: `_record_capture` calls `record_purchase`. `app/store.py`: cart items now keep the brand. `app/mock_agent.py`: `PREFER`, `DISLIKE`, `SAVED`, `preference_args`.

**How it works.**
1. Every agent turn builds the system prompt from the fixed rules plus `prompt_block(user_id)`: the user's saved preferences as `- [id] +0.50 text`, strongest first.
2. The prompt tells the model to call `remember_preference(text, about_id?, stance?)` for lasting preferences and reasons for rejecting a product; not for one-purchase conditions, and never for health, religion or other sensitive details.
3. `remember`: with `about_id`, that preference of this user gets +0.1 (`supports`) or -0.2 (`contradicts`), evidence count +1. Without it, a preference with the same text (case-insensitive) is updated the same way; otherwise a new row is inserted at +0.5 (or -0.5 for a new `contradicts`). Strength is clamped to [-1, 1] and rounded to 2 decimals. An unknown or foreign ID, an empty text or a bad stance raises `ValueError`, which goes back to the model as a tool error.
4. When a capture is recorded as `COMPLETED`, `record_purchase` calls `remember(user, "Likes the brand X")` for each brand in the order items, so buying the same brand again confirms it.
5. Keyless mock: "I prefer / always buy / love X" saves or confirms "Prefers X"; "I don't like X (anymore)" contradicts a saved preference that mentions X (ID read from the system prompt), or saves "Dislikes X".

**Why.** The agent writes memory itself through a tool ("hot path"), as LangMem and the OpenAI cookbook do; updates target an ID shown in the prompt, so code never has to guess which sentence matches. The strength rule comes from the requirements (MARS); the starting value 0.5 is our choice. See `docs/decisions.md` (F18-F20).

**Verified.** `tests/test_memory.py`: new row at 0.5, same text confirms (+0.1), confirm/contradict by ID, clamping at 1 and -1 without float drift, bad input and another user's ID refused, per-user lists sorted by strength, prompt block format, two purchases of one brand give 0.6 with 2 pieces of evidence, a cancelled payment writes nothing, mock agent saves then contradicts by ID, tool errors returned to the model. By hand (keyless): "I always buy Soundcore" replied "Noted. I will remember: Prefers Soundcore".

**Limits / not verified.** Whether a real model saves the right things (and skips sensitive or one-off ones) is a prompt rule, not checked in code, and not measured. The mock understands only the phrasings above, and a request that contains "I prefer X" is treated as a preference statement rather than a search.

## F19 Preference memory: use (`app/recommend.py`, `app/agent.py`, `app/memory.py`, `eval/`)

**What it does.** At the start of a conversation the user's 3 strongest saved preferences become a profile that the ranker sees as soft preferences; when the ranker says a memory influenced a pick, the reason shown to the user names that memory.

**Where.** `app/memory.py`: `profile`. `app/store.py`: `Session.memory_profile`, `new_conversation`. `app/agent.py`: profile loaded in `handle_message`, attached in `tool_recommend`. `app/recommend.py`: `use_memory` flag, `_memory_section`, `memory` field in `parse_ranking` / `aggregate`, reason suffix and `memory_used` in `recommend`, `_mock_memory_match`. `app/main.py`: `POST /api/conversation/new`. Page: New conversation button. Eval: 4 `preference` requests, version "+ memory", `metrics.respects_preference`.

**How it works.**
1. On the first message of a session, `handle_message` stores `memory.profile(user)`: up to 3 preferences with strength > 0, strongest first. It stays fixed for that conversation. "New conversation" replaces the session (history, search results, carts) but keeps orders and memory.
2. `tool_recommend` attaches the profile to the request; the model never supplies it, and the prompt tells it not to copy memories into `recommend`.
3. With `use_memory` on (app default), `rank` adds a section "Remembered preferences from earlier conversations (soft, the current request wins)" listing `[m<id>] text`. Search queries and the hard filter never see memory, so budget and exclusions come only from the current request.
4. The ranker may put `"memory": "m<id>"` on an entry; `parse_ranking` keeps it only if it is one of the given IDs; `aggregate` keeps the memory of the entry whose reason it keeps.
5. `recommend` appends `Based on what I remember: "<text>".` to that product's reason in code and sets `memory_used`.
6. Keyless mock ranking: products whose title or brand contains a content word of a positive memory move to the front with that memory ID.
7. Eval: each preference test runs conversation 1 ("I always buy Sony electronics.") through the agent loop into a throwaway database, stores the saved profile and step 1 of conversation 2 in the snapshot, and replays conversation 2 with memory off (all earlier versions) and on ("+ memory"). Adherence = the top recommendation's title or brand contains the expected keyword.

**Why.** The ranker gets a short profile rather than raw chat history (MARS, appendix A), and memory is kept out of search and filtering so current constraints always win. Adding the memory text to the reason in code guarantees the acceptance rule "the reason says which memory was used". See `docs/decisions.md` (F18-F20).

**Verified.** `tests/test_memory.py`: profile is the top 3 positive; the ranker prompt contains the memory section; a valid memory ID adds the memory text to the reason and an unknown one is ignored; with memory off the section is absent; memory cannot rescue an over-budget product; keyless end to end: "I always buy Soundcore", New conversation, then headphones put Soundcore first with the memory in the reason. `tests/test_eval.py`: 4 preference requests, adherence on the top product. By hand: the same flow in the browser; `python -m eval.run_eval --name mock-f19 --runs 1` (keyless) appended the preference entries to the mock snapshot and printed the memory column (mock numbers, not results).

**Limits / not verified.** No real model run: whether the ranker uses memories sensibly, and whether conversation 1 saves them, is unmeasured. The profile is fixed at the start of a conversation, so a preference saved mid-conversation applies from the next one. Adherence checks only the top product and a keyword in title or brand. Memory is in SQLite on the server, so a Render restart loses it.

## F20 Preference memory: view and delete (`app/main.py`, `app/memory.py`, `static/index.html`)

**What it does.** A "What I remember" panel lists every saved preference of the user with its strength and a Delete button.

**Where.** `app/memory.py`: `delete`. `app/main.py`: `GET /api/memory`, `DELETE /api/memory/{id}`. `static/index.html`: `loadMemory`, the `#memory` panel; `api()` now takes an optional HTTP method.

**How it works.**
1. On page load, and after any chat turn where a tool changed memory (`memory_changed`), the page calls `GET /api/memory`, which returns this user's entries (ID, text, strength, evidence count), strongest first.
2. Each entry is shown with `textContent` (never as HTML) and a Delete button that disables itself on click.
3. `DELETE /api/memory/{id}` runs `DELETE ... WHERE id = ? AND user_id = ?`, so a user can only delete their own entries (otherwise 404). It also removes the entry from the current conversation's profile, so it stops influencing recommendations at once.

**Why.** Users must be able to see and remove what is kept about them; filtering by the cookie's user ID in SQL is the same ownership rule as for orders. Deletion is a hard delete, because the user asked for that entry to be gone.

**Verified.** `tests/test_memory.py`: list shows the saved entry; another browser sees nothing and cannot delete it (404); delete works once, then 404; a deleted memory stops appearing in reasons in the same conversation. By hand (keyless): the panel showed "Prefers Soundcore (strength 0.5)"; Delete emptied the list.

**Limits.** No undo. Strength is shown as a raw number. Not checked at phone width.

## F21 Multi-item cart (`app/store.py`, `app/agent.py`, `app/main.py`, `static/index.html`)

**What it does.** A cart can hold 1 to 6 different products, each with a quantity. The server prices every line, sums the total in cents and refuses the whole cart if any line breaks a rule or the total is over the budget. Since the second F21 commit, PayPal also receives one line item per product (see the F9/F10 entry).

**Where.** `app/store.py`: `create_cart_items`, `_cart_item`, `MAX_CART_LINES`; `create_cart` is now a one-line wrapper. `app/agent.py`: `prepare_cart` tool schema (optional `items`), `cart_lines`, `tool_prepare_cart`, `cart_view`. `app/main.py`: `CartIn`, `CartLine`, `POST /api/cart`. `app/mock_agent.py`: the cart sentence in `summarize`. `static/index.html`: `showSummary`.

**How it works.**
1. Input is a list of `(product_id, quantity)`. The model sends either `product_id`/`quantity` or `items`; `cart_lines` turns both into lines and reads nothing else, so a price in the arguments is ignored. The HTTP endpoint takes exactly one of `product_id` or `items` and returns 400 otherwise.
2. `create_cart_items` first refuses an empty list, more than 6 lines and a repeated product ID ("set its quantity instead"). These checks need no catalog call, so they run first.
3. Each line then goes through `_cart_item`, the same checks and order as the F8 single-product cart: known to this session's searches, read back from the catalog, in stock with a USD price, quantity an int from 1 to 10. The first failing line raises `CartError` and no cart is stored.
4. Total = sum of unit price x quantity. If the session has a budget and the total is above it, the cart is refused with the same message as F8, even when every line alone is under the budget.
5. A line whose refreshed price differs from the searched one carries its own `price_was_cents`. The tool result gives the model each title with its quantity, the total, and one price note per changed item; the page shows one row per item (title, unit price x quantity), the server's total, then one price-change line per changed item.
6. Confirm is unchanged: it copies `items` and `total_cents` to the order row, so a multi-item order is captured, shown and refunded (whole order, F16) like a single-item one. An item's `price_was_cents`, when present, is copied into the order's `items` snapshot with the rest of the item; nothing reads it there.

**Why.** One bad line refuses the whole cart instead of dropping that line, so the user never sees a total for a set they did not choose. The budget is checked on the total because that is what the user pays. Duplicates are refused rather than merged so that one line always means one product, which refund by line (F23) relies on. The limit of 6 lines matches the set-recommendation ceiling and keeps the PayPal body small. Keeping `create_cart` as a wrapper left every existing caller and test of F8-F16 working unchanged.

**Verified.** `tests/test_store.py`: two-line total in cents; total over budget refused although each line fits; unknown ID in the second line refuses the cart and stores nothing; duplicate ID, 7 lines and an empty list refused; 6 lines allowed; a price change recorded on the right item. `tests/test_agent.py`: `prepare_cart` with `items` sums server prices and ignores a model price; an invented ID in `items` is an error and no cart is stored. `tests/test_api.py`: `POST /api/cart` with `items`; both fields or neither is 400; a full mock purchase of a two-item cart ends `COMPLETED` with both items and the summed amount. By hand (keyless, server restarted): single-product flow unchanged (yoga mat, Choose, Confirm, mock approve, status, refund to `REFUNDED`); a two-item cart posted to `/api/cart` (2 x $59.99 + 1 x $79.99) showed one row per item and $199.97, mock PayPal asked for 199.97 USD, the order ended `COMPLETED` with both items and was refunded in full; over-budget, both-fields and duplicate requests returned 400 with their messages.

**Limits.** The page has no way to build a multi-item cart yet: the Choose button sends one product, and the keyless mock agent never sends `items` (set recommendation, F22, adds both). The price-change line on the page was checked only by unit test, because mock catalog prices never change. A refund is still for the whole order until F23. The real model has not been asked to use `items`.
