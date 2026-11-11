# Design decisions

Written before implementing a feature that involves a real design choice: what was looked at, how each does it, what we chose and why.

## F5 Parsing and validating the ranking output

**Looked at (2026-11-11)**
- RankGPT, `rank_gpt.py` (https://github.com/sunnweiwei/RankGPT/blob/main/rank_gpt.py). The model outputs a permutation like `[2] > [1] > [3]`. `clean_response` turns every non-digit into a space, `remove_duplicate` keeps the first occurrence, `receive_permutation` drops out-of-range numbers and appends the items the model omitted in their original order. No exception handling. License could not be confirmed (the LICENSE URL returned 404).
- castorini/rank_llm, Apache-2.0 (https://github.com/castorini/rank_llm). `clean_ranking_response` in `src/rank_llm/rerank/listwise/response_utils.py` splits off a `</think>` block and strips non-digits; `receive_permutation` in `listwise_rankllm.py` dedupes (first kept), filters to the window, appends omitted items in original order, and on any exception falls back to the original order.

**Chosen.** The same three ideas: keep the first occurrence of an ID, drop IDs that are not candidates, and fall back to search order when the output cannot be used. Differences:
- Our output is a JSON object of product IDs with a one-sentence reason each, after a free-text reasoning passage (requirements F5), not a digit permutation. So instead of stripping non-digits we find the last `{"ranking"` in the reply and read one JSON value from there with `json.JSONDecoder().raw_decode`, which ignores trailing text such as a closing code fence.
- A parse failure, a blank reply, or a ranking with no valid ID is a format error: one retry (shared rule in `llm.ask`), then search order. rank_llm falls back immediately; the requirements ask for one retry.
- Omitted candidates are not appended to the ranking (the model may list up to 6 on purpose). They are used only if fewer than 3 products were ranked, to fill the remaining places in search order.

No code was copied.

## F1, F2 Agent tool loop

**Looked at (2026-11-11)**
- DeepSeek tool-calls guide (https://api-docs.deepseek.com/guides/tool_calls). Chat Completions loop: append `choices[0].message` to the history, then one `{"role": "tool", "tool_call_id", "content"}` per call, and call again until the reply has no `tool_calls`. Strict schemas exist only on the beta base URL. The thinking-mode guide (https://api-docs.deepseek.com/guides/thinking_mode) says that with `tools` present, `reasoning_content` must be sent back on every later request or the API returns 400, and thinking can be turned off with `{"thinking": {"type": "disabled"}}`.
- OpenAI function-calling guide (https://developers.openai.com/api/docs/guides/function-calling). Same loop shape (Responses API wording): append the model output, append one output per call, call again. Tool output is a string whose format is up to the app; the model may call several tools in one turn.
- OpenAI Agents SDK, MIT (https://openai.github.io/openai-agents-python/running_agents/). The run loop has a `max_turns` limit and raises `MaxTurnsExceeded` when it is hit (a handler can return a final output instead). Unknown tools raise by default, with an option to return the error to the model and run it again.

**Chosen.** The plain Chat Completions loop from the DeepSeek guide, written by hand (no SDK):
- Append the assistant message exactly as returned (keeps `reasoning_content` and any other provider field), then one `tool` message per call, in order, handling every call in a turn.
- At most 5 tool rounds per user message. Instead of raising like the Agents SDK, the loop appends a fixed assistant reply, so the user always gets an answer and the history stays valid (every `tool_calls` message is followed by its tool messages).
- Unknown tool names, bad argument JSON and exceptions inside a tool all become `{"error": ...}` tool messages (the Agents SDK's "return error to model" option), so the model can correct itself and the request never crashes.
- No strict schemas (beta-only on DeepSeek). Thinking mode is turned off through `LLM_EXTRA_BODY`, not in code.
- The budget question (F2) is a prompt rule; whether the model follows it is measured by the eval's ask accuracy. The budget itself is enforced in code (F4 and the cart check).

No code was copied.

## F9-F14 PayPal order creation, return handling, pre-capture check, idempotency

**Looked at (2026-11-11)**
- PayPal's official standard-integration sample, Apache-2.0 (https://github.com/paypal-examples/docs-examples/tree/main/standard-integration/server; read `server/python/server.py` and `server/node/server.js`). Create: `intent: CAPTURE`, one purchase unit with a hard-coded amount, no `PayPal-Request-Id`, no return/cancel URLs (it uses the JS SDK popup, not a redirect). Capture: called directly with the order ID from the browser; the order is not read back first. Errors become a generic HTTP 500. The SDK handles the access token.
- Orders v2 reference (https://developer.paypal.com/api/orders/v2/orders-create, `.../orders-capture`) and error list (https://developer.paypal.com/api/rest/reference/orders/v2/errors/). `PayPal-Request-Id` is "for idempotency purposes"; the errors page lists `ORDER_NOT_APPROVED`, `INSTRUMENT_DECLINED` and `ORDER_ALREADY_CAPTURED` for capture as `UNPROCESSABLE_ENTITY`, and `PAYPAL_REQUEST_ID_REQUIRED` for create with a `payment_source`. The `experience_context` and `payer-action` details could not be re-read on the rendered page this time; they are taken from requirements section 8.
- Idempotency guideline (https://developer.paypal.com/reference/guidelines/idempotency/). Retrying with the same `PayPal-Request-Id` returns the latest status of the earlier request; omitting it duplicates the request; two simultaneous requests with the same ID may fail the second; retention is per API.
- Refund reference (https://developer.paypal.com/api/payments/v2/captures-refund). Empty body for a full refund; the example response has `status: COMPLETED`. The 45-day retention figure in the requirements was not found on the pages read.

**Chosen.**
- Redirect flow with `payment_source.paypal.experience_context` (return/cancel URLs, `PAY_NOW`, `NO_SHIPPING`) and redirect to the `payer-action` link, because it needs no PayPal JavaScript on the page and works as plain navigation.
- Deterministic request IDs `create-{cart_id}`, `capture-{order_id}`, `refund-{order_id}`, so a retry repeats the same request. The sample sends none.
- The local order row is the first guard: Confirm returns the existing order for a cart (`cart_id` is `UNIQUE`), capture runs only from `CREATED`, refund only from `COMPLETED`. A process-wide lock around these actions (single worker) stops a double click from racing past the status check; the request ID is the second guard.
- Read the order back before capture and require `APPROVED` plus amount and currency equal to the order row (amounts parsed with `Decimal`). The sample does not do this; it is this project's own addition (requirements section 6).
- Paid only when `purchase_units[0].payments.captures[0].status == "COMPLETED"`. Error issues are read from `details[0].issue`, falling back to `name`.
- The PayPal order ID is taken from our order row, never from the return URL's query string; the return URL carries only our local order ID, and the row must belong to the cookie's user.

No code was copied.

## M4 Eval metric computation (NDCG@3 and unlabeled products)

**Looked at (2026-11-11)**
- trec_eval `m_ndcg_cut.c` (https://raw.githubusercontent.com/usnistgov/trec_eval/master/m_ndcg_cut.c), used through pytrec_eval (MIT, https://github.com/cvangysel/pytrec_eval). Gain is the relevance value itself (linear); discount is log2(rank + 1); the ideal DCG is built from all judged relevance levels of the topic, not from the retrieved list; when the ideal DCG is 0 the score stays 0. A retrieved document with no positive judgment adds nothing but keeps its rank, so unjudged documents are effectively scored as non-relevant.
- ir-measures, Apache-2.0 (https://github.com/terrierteam/ir_measures, https://ir-measur.es/en/latest/measures.html). nDCG has `cutoff`, `dcg`, `gains` and `judged_only` options; it also offers `Judged@k`, the share of the top k that has a judgment, to show how complete the labels are.
- scikit-learn `ndcg_score` (BSD-3, https://scikit-learn.org/stable/modules/generated/sklearn.metrics.ndcg_score.html). Its worked example uses raw relevance values (linear gain). The page read did not confirm the log base or the all-zero case.

**Chosen.** Linear gain (labels 0, 1, 2), discount `log2(position + 1)`, ideal DCG from the 3 highest labels among all labelled products of the request, and 0 when every label is 0, which matches trec_eval. One deliberate difference: a recommended product with no label is **not** scored as 0 (trec_eval's behaviour). The request is marked incomplete and the product is listed for labelling, as requirements section 9 asks, because pooling means an unlabeled product is a gap in the labels, not evidence of irrelevance. This plays the role of ir-measures' `Judged@k` check. About 10 lines of our own code instead of adding pytrec_eval or scikit-learn as a dependency.

No code was copied.

## F17 Multi-shuffle ranking: aggregating several rankings

**Looked at (2026-11-11)**
- Permutation Self-Consistency, MIT (https://github.com/castorini/perm-sc; paper https://aclanthology.org/2024.naacl-long.129/). Shuffle the input list several times with the instructions fixed, rank each, then take the central ranking that minimises Kendall tau distance to all of them (Kemeny-Young). The library also offers Borda, reciprocal rank fusion and local search; missing items are marked -1 and not every aggregator supports them.
- castorini/rank_llm, Apache-2.0 (https://github.com/castorini/rank_llm). Has a `--num-passes` option for running the reranker several times; the README and release notes read do not say how passes are combined.

**Chosen.** 3 shuffles (configurable through `rank_shuffles`; 1 is exactly F5), ranked in parallel threads, aggregated by **mean rank**, a Borda-style method. A product that a ranking does not list gets rank 7 (one place below the longest allowed list of 6), as requirements F17 specify; this gives missing items a defined value instead of the -1 marker that some perm-sc aggregators cannot use. Ties keep the order of first appearance. Kemeny-Young is rejected: it is NP-hard in general and much harder to explain line by line, and with 3 rankings of at most 6 items the difference is small. The shuffles use seed, seed+1, seed+2, all logged. The reason shown for a product comes from the ranking that placed it highest.

No code was copied.

## F18-F20 Preference memory

**Looked at (2026-11-11)**
- mem0, Apache-2.0 (https://github.com/mem0ai/mem0, https://docs.mem0.ai/core-concepts/memory-operations/add). An LLM extracts facts; the current algorithm is add-only (nothing overwritten); retrieval is embedding similarity scoped by `user_id` with `top_k`. No stored strength field.
- LangMem, MIT (https://github.com/langchain-ai/langmem, https://langchain-ai.github.io/langmem/guides/memory_tools/). "Hot path": the agent itself calls a manage-memory tool during the conversation; alternatively a background manager extracts memories after each message. Items are keyed by ID in a per-user namespace.
- OpenAI cookbook, "Context Engineering for Personalization" (https://developers.openai.com/cookbook/examples/agents_sdk/context_personalization.md). The model calls a `save_memory_note` tool; at the start of a run the notes are rendered into the system prompt as a short capped list. Confidence scores are only mentioned as an option. No user view or delete.

**Chosen.**
- Write on the hot path, like LangMem and the cookbook: a `remember_preference` tool (proposal tier; no click needed because it moves no money and the user can delete entries in F20). One SQLite table: `user_id`, `text`, `strength`, `evidence_count`, `updated_at`.
- Updates by ID: the system prompt lists the user's memories with IDs, and the tool takes an optional `about_id` with `supports` or `contradicts`. Supports adds 0.1, contradicts subtracts 0.2, clamped to [-1, 1] (requirements, from MARS in appendix A). A new preference starts at 0.5. The strength score is our own field; none of the three sources stores one.
- A completed purchase writes or supports "Likes the brand X" from code, matched by exact text, because the server, not the model, sees the capture.
- Use: no embedding search (one short list per user is enough, and it needs no new dependency). At the start of a conversation the 3 strongest positive preferences become a profile that only the ranker sees, as soft preferences below the current request; hard constraints come only from the current request. The ranker may name the memory it used; code then appends that memory's text to the reason, so the reason always says which memory was used.
- A "What I remember" panel lists every entry with a delete button (none of the sources covers this; required by F20).

No code was copied.

## Channel3 response handling: ambiguous fields and retries

**Looked at (2026-11-11)** — Channel3's own docs, since this is about matching one provider:
- Search reference, `components.schemas.Product` (https://channel3.mintlify.dev/docs/api-reference/v1/search.md): the price is `offers[].price.price`, and the filter description calls it "dollars and cents". Filter defaults are `conditions: ["new"]` and `availability: ["InStock"]`.
- Offer guide (https://channel3.mintlify.dev/docs/guides/offer.md): a product passes a filter when at least one offer matches, but the response still carries every offer, including non-matching ones. Offer `url` is an attributed buy link.
- Search guide (https://channel3.mintlify.dev/docs/guides/search.md): its examples write `offers[].price.amount`, which contradicts the schema, and its filter table lists availability values (`LimitedAvailability`, `PreOrder`, `BackOrder`, `SoldOut`) that the schema does not accept.
- Errors (https://channel3.mintlify.dev/docs/conversations/errors.md) and rate limits (https://channel3.mintlify.dev/docs/faq/rate-limits.md): body `{"error": {"code", "message"}}`; 429 carries `Retry-After: 5`; 503 is marked retryable.
- Caching guide (https://channel3.mintlify.dev/docs/guides/caching.md): prices, availability and offers must be refreshed before being shown; offer URLs must not be cached.

**Chosen.**
- **Price field**: read `price.price`, fall back to `price.amount`. Trusting only the schema would mean every product looks like it has no USD offer, and the app would recommend nothing, with no obvious error. Two lines of code remove that risk until a real response settles it.
- **Availability**: an offer counts as buyable unless its value is one of `OutOfStock`, `SoldOut`, `PreOrder`, `BackOrder`. The docs say an offer with no availability data is in stock, so treating missing as out of stock (the earlier behaviour) would silently drop valid products. An unseen value is logged once and treated as in stock, which is how a real response will teach us the real set. `PreOrder` and `BackOrder` count as not buyable, because this app takes payment immediately.
- **Retries**: one retry on 429 and 5xx, honouring `Retry-After` capped at 10 seconds. Chosen over a retry library (no new dependency) and over retrying forever (a demo must fail fast). Network errors are not retried, because the docs say nothing about them. Error messages carry Channel3's `error.code`, so `insufficient_credits` is distinguishable from `unauthorized` when a key is first used.
- **`config.country = "US"`** is now sent with the currency, so language and currency inference is deterministic rather than guessed from the caller.

No code was copied.

## F8 Refreshing the price before a cart is priced

**Looked at (2026-11-11)**
- Channel3 caching guide (https://channel3.mintlify.dev/docs/guides/caching.md): product IDs may be cached indefinitely, but prices, availability and offers must be refreshed before being shown, and offer URLs must not be cached at all.
- Channel3 product-detail guide (https://channel3.mintlify.dev/docs/guides/product-detail.md): cache `product.id` from a search, then retrieve the product before showing a price or a buy link. Search results may omit live stock.
- Channel3 pricing (https://channel3.mintlify.dev/docs/pricing.md): `GET /v1/products/{id}` is free, while a search costs one credit.
- PayPal's own sample server (already recorded under F9-F14) does the opposite for orders: it captures without reading anything back. Our pre-capture check was added for the same reason as this one.

**Chosen.** `store.create_cart` re-reads the product through `catalog.get_product` and prices the cart from that, not from the stored search result. The session's copy is replaced, so the budget check and the order row all use the fresh figure.
- Refusing rather than falling back on failure: if the catalog cannot be reached, no cart is created and the user is asked to try again. Quoting a price we could not confirm is the one outcome a payment demo should not have, and the HTTP layer has already retried once.
- A product that is gone (404) or newly out of stock is refused with its own message.
- A price that moved is not an error: the cart carries `price_was_cents`, and the page and the agent both say the price changed. Silently charging a different number than the card showed would be worse than saying so.
- The alternative of refreshing inside the two call sites (the agent tool and the Choose endpoint) was rejected: a third call site could forget, and pricing belongs with the other cart rules.
- Cost: one free call per Choose click. The 15-minute cart quote is unchanged; it now starts from a confirmed price.

No code was copied.
