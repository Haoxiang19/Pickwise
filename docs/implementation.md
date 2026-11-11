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
2. Mock search: lowercase word sets with stopwords removed and a crude plural fold; score = shared words between query and title/description/category/brand; top `limit` by score, catalog order on ties.
3. `normalize` keeps only USD offers with a parseable `price.price` (read with `Decimal`), picks the cheapest in-stock one. If none is in stock it keeps the cheapest USD offer with `in_stock=False`; with no USD offer at all, `price_cents` and `currency` are `None`. These two cases map to the "out of stock" and "no in-stock USD offer" rejection reasons in F4.
4. Main image is the one with `is_main_image`, else the first; brand is `brands[0].name`; category is `category.title`.
5. Channel3 HTTP or parse failures raise `CatalogError`.

**Why.** Keeping the mock in Channel3's raw shape means the same `normalize` code runs in tests and keyless mode, so the mapping is exercised even without a key. The budget is not sent as a Channel3 filter, so over-budget items can be shown as rejected.

**Verified.** `tests/test_catalog.py`: cheapest in-stock USD offer chosen, out-of-stock and non-USD cases, missing fields, mock search, Channel3 request shape (with a fake HTTP call).

**Limits / not verified.** No real Channel3 call yet. The field names and the dollar unit of `offers[].price.price` come from the docs only; a unit mistake would be a 100x price error and must be checked against a real response. The mock search is word overlap only.

## F3 Multi-query search, F4 Hard-constraint filter (`app/recommend.py`)

**What it does.** Runs each search query from the structured request, merges the results, and removes products that break a hard constraint, recording why.

**Where.** `app/recommend.py`: `parse_request`, `search_all`, `rejection`, `round_robin`, `hard_filter`.

**How it works.**
1. `parse_request(args)` cleans the model's tool arguments: `budget_usd` becomes `budget_cents` through `to_cents` (`None` means no limit), empty strings are dropped, at most 4 queries are kept, and if there are none the raw request is the only query. An empty `raw_request` raises `ValueError`.
2. `search_all(queries)` calls `catalog.search(q, 10)` per query and merges by product ID with `dict.setdefault`, so a product returned by several queries keeps the first query's index (`query_index`).
3. `rejection(p, budget_cents, must_not)` checks in order: no USD offer, out of stock, price above budget (skipped when the budget is `None`), and must-not keywords. Keywords match title and brand only, case-insensitive, whole word (`\b...\b`). It returns a `(kind, reason)` pair; `kind` is used later to count reasons.
4. `hard_filter` splits products into passing and rejected (with ID, title, price, kind, reason), interleaves the passing ones round-robin by source query, and keeps the first 20.

**Why.** Constraints are enforced in code, not in the prompt, so a model mistake cannot recommend an over-budget item. Round-robin before the 20-item cap stops the first query from filling every slot. The description is not checked for must-not words because phrases like "not leather" would cause false matches (requirements section 4).

**Verified.** `tests/test_recommend.py`: budget conversion and list cleaning, merge keeps first query, each rejection reason, budget equal passes, no-budget skips the check, whole-word and brand matching, description ignored, round-robin order and the 20 cap. Run by hand on the mock catalog: 3 queries, 15 products found, 9 passed, 6 rejected with the expected reasons.

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
6. `recommend(request, flags, search_fn, seed)` runs search, filter, rank (skipped when `reasoning_rank` is off, which means search order), pick, and builds each recommendation (ID, title, brand, price in cents, URL, image, reason; a default reason names the source query). If fewer than 3 remain, `note` says how many were removed, grouped by reason, and suggests a change. One log line records queries, seed, candidates, rejections, ranking and picks.
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

**Where.** `app/store.py`: `create_cart`, `get_valid_cart`, `CartError`, `Session.carts`. `app/agent.py`: `prepare_cart` tool (`tool_prepare_cart`), `cart_view`. `app/main.py`: `POST /api/cart` (the card's Choose button). `static/index.html`: `showSummary`.

**How it works.**
1. The model calls `prepare_cart(product_id, quantity)`, or the user clicks Choose on a card, which posts the same two fields.
2. `create_cart` looks the ID up in `session.products` (only products returned by a search in this session); unknown IDs are refused.
3. It refuses products that are out of stock, have no price or are not USD, and quantities outside 1-10.
4. Total = server unit price x quantity, in cents. If the session has a budget and the total is above it, the cart is refused; with no budget the check is skipped.
5. The cart gets a random ID, a one-item snapshot (product ID, title, unit price, quantity), the total, `USD`, and `expires_at` = now + 15 minutes. `get_valid_cart` (used by Confirm in F9) refuses unknown or expired carts.
6. Rule errors are `CartError`, shown to the user (HTTP 400) or returned to the model as a tool error.
7. The page shows product, unit price, quantity and total from the server's response.

**Why.** The model only names a product ID, so it cannot set a price; any price field in its arguments is ignored. Carts are per session, so one user cannot order with another user's search results. The cart is only a quote: Confirm (F9) copies it to the order row, which then becomes the reference.

**Verified.** `tests/test_store.py`: integer-cent total, unknown ID, quantity bounds and type, unavailable products, budget on the total, no-budget skip, expiry at 15 minutes. `tests/test_agent.py`: "take the second one" prepares the right cart at the server price; a model-supplied price is ignored; an invented ID returns an error. `tests/test_api.py`: Choose endpoint works, and another browser cannot use this session's product. By hand (keyless): "a yoga mat under $120", Choose on the second card shows Lululemon The Mat 5mm, $108.00, quantity 1, total $108.00.

**Limits.** One product per cart (multiple items is P2). Expired carts stay in memory until restart. The quantity can only be changed by asking the agent; the page always sends 1.
