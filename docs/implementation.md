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
