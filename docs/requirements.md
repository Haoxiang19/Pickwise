# Requirements: PayPal Shopping Agent

This file defines what to build. How to work is in `CLAUDE.md` at the repository root.

## 1. Overview

Build a conversational shopping agent: the user describes a need in one sentence, the agent recommends 3 products, the user confirms and pays through the PayPal sandbox, and can later check the order or get a refund.

- **Hackathon**: PayPal AI Hackathon 2026. Deadline November 12, 2026, 12:00 pm Pacific Time (2:00 pm Houston time).
- **Main purpose**: a resume project. The design must be easy to explain and backed by eval numbers.
- **Differentiator**: evaluation data that shows recommendation quality.
- **Environment**: PayPal sandbox only. No real money moves.
- **Nature of orders**: products come from outside retailers, while the payment goes to this project's own sandbox merchant account. Orders are therefore a concierge-style simulation. The demo and README must say so.

## 2. User flow

1. The user describes a need.
2. If no budget is given, the agent asks one question and searches only after getting it.
3. The agent shows 3 recommendations, each with a price and a one-sentence reason, and lets the user see which products were ruled out and why.
4. The user can refine ("cheaper", "a different brand") and the agent recommends again.
5. The user picks a product, sees an order summary, and clicks Confirm.
6. The page redirects to PayPal, where the user logs in and approves the payment.
7. Back on the site, the server verifies and captures, then shows success and the order ID.
8. Later, the user can ask for the order status, or request a refund and confirm it.

Branches: the user cancels on PayPal and is told nothing was charged; the capture fails and the user is told why, with the order not marked as paid.

## 3. Functional requirements

Priorities: P0 is required. P1 starts only after all of P0 works against the real services. P2 is done only with time to spare.

### P0

| ID | Stage | Feature | Acceptance criteria |
| --- | --- | --- | --- |
| F1 | Understand | Parse the request | The user's words are split into budget, must-have, must-not, and preferences |
| F2 | Understand | Ask when the budget is missing | With no budget, ask exactly one question and do not search; with a budget, search directly. If the user answers that there is no limit, the budget is empty, the budget checks are skipped, and the agent does not ask again |
| F3 | Recommend | Multi-query search | Each request produces 3 to 4 concrete search queries; results are merged and de-duplicated |
| F4 | Recommend | Hard-constraint filter | Removed in code, with the reason recorded: over-budget products, out-of-stock products, products with no in-stock USD offer, and products that match a must-not keyword |
| F5 | Recommend | Reasoning rank | The model reasons first, then ranks, outputting product IDs only; candidates are shuffled first; unknown IDs are dropped |
| F6 | Recommend | Show recommendations | 3 products, each with a price and a one-sentence reason; rejected products and reasons can be expanded |
| F7 | Recommend | Refine from feedback | After a new condition, recommend again under it while keeping earlier conditions |
| F8 | Confirm | Order summary | Shows product, quantity and total; the total is computed by the server |
| F9 | Confirm | User confirmation | A PayPal order is created only after the user clicks Confirm |
| F10 | Pay | Create order and redirect | Create the order with Orders v2 and redirect to the PayPal approval page |
| F11 | Pay | Verify, then capture | On return, check that the order is approved and the amount equals the amount stored on the order row at Confirm, then capture |
| F12 | Pay | No double charge | Repeated clicks or page refreshes never create a second order or capture |
| F13 | Pay | Cancel and failure messages | On cancel or failure, say nothing was charged; the order is not marked as paid |
| F14 | Pay | Success page | Shows payment success and the order ID |
| F15 | After-sale | Order status | When asked, return order ID, status and amount |
| F16 | After-sale | Refund | The agent drafts a refund; PayPal is called only after the user confirms; a refunded order cannot be refunded again |

### P1

| ID | Feature | Acceptance criteria |
| --- | --- | --- |
| F17 | Multi-shuffle ranking | Shuffle candidates 3 times, rank 3 times in parallel, aggregate by mean rank; a candidate that a ranking does not list gets rank 7, one place below the longest allowed list; the count is configurable, and 1 equals F5 |
| F18 | Preference memory: write | Write or update a preference when the user states a long-term preference, rejects a recommendation with a reason, or completes a purchase |
| F19 | Preference memory: use | At the start of a new conversation, the strongest preferences enter the recommendation as soft preferences; the reason text says which memory was used |
| F20 | Preference memory: view and delete | A "What I remember" panel lets the user see and delete each entry |

### P2

Side-by-side comparison table; an LLM judge with its agreement rate against human labels; eval for multi-turn refinement; structured product profiles; separate models for query generation and ranking.

| ID | Feature | Acceptance criteria |
| --- | --- | --- |
| F21 | Multi-item cart | A cart holds 1 to 6 different products, each with a quantity; the total is the sum computed by the server in integer cents; a total over the budget refuses the whole cart; one unknown, unavailable or duplicate product refuses the whole cart; the PayPal order carries one line item per product and an item total equal to the amount |
| F22 | Set recommendation | For a request naming 2 to 6 different products under one budget, each item is searched and ranked on its own; code picks the set with the lowest rank sum among sets whose total is within the budget; if no set can fit, no model ranking is run and the user is told the price of the cheapest set |

## 4. Recommendation pipeline spec

| Step | Owner | Input | Output |
| --- | --- | --- | --- |
| 1. Understand | Model | User message, chat history, preference profile (P1) | One clarifying question, or a structured request: raw request, budget, must-have, must-not (as short keywords), preferences, 3 to 4 search queries |
| 2. Search | Code | Search queries | 10 results per query (`limit: 10`), merged and de-duplicated by product ID; a product returned by several queries belongs to the first query that returned it |
| 3. Hard filter | Code | Candidates, budget, must-not keywords | Passing candidates (round-robin across queries, at most 20) and a rejected list with reasons |
| 4. Rank | Model | Structured request, shuffled candidates (each with only ID, title, price, brand, truncated description) | A reasoning passage, then one line of JSON: at most 6 product IDs, each with a one-sentence reason |
| 5. Pick top 3 | Code | Ranking, candidates | 3 recommendations; when there are 3 or more queries, at most one per source query; if that rule leaves fewer than 3, the remaining places are filled in rank order |
| 6. Reply | Model | Recommendations returned by the tool | A short reply to the user |

Rules:

- The model is called only in steps 1, 4 and 6. One recommendation is 3 model calls under P0.
- Ranking output must be validated: IDs not among the candidates are dropped; on a parse failure retry once, then fall back to search order.
- Switches for the eval: `multi_query` (off means one search with the user's raw words), `reasoning_rank` (off means search order), `rank_shuffles` (1 or 3), `use_memory`.
- What the user says now overrides preference memory. Hard constraints such as budget come only from the current request.
- Must-not rule: a product is rejected when any must-not keyword appears in its title or brand (case-insensitive, whole word). The description is not checked, because phrases such as "not leather" would cause false matches.
- Fewer than 3 candidates after the hard filter: show the ones that passed, say how many were removed and why, and suggest a change (for example a higher budget). With none left, say so and recommend nothing.
- The shuffle in step 4 uses a seed that is written to the request log, so a run can be repeated.
- Agent loop limit: at most 5 tool rounds per user message. A tool error or an unknown tool name is returned to the model as a tool message, not raised. When the limit is reached, the agent sends a fixed fallback reply.

## 5. Model interface requirements

- All model calls go through `app/llm.py`.
- Use the OpenAI-compatible chat and function-calling format. Config: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. Switching models is a config change only.
- No feature unique to a single provider.
- Record input and output token counts per call, for cost reporting in the eval. Read them from `usage.prompt_tokens` and `usage.completion_tokens`; if the field is missing, record 0 and do not fail.
- With no key configured, use a rule-based mock.
- `LLM_EXTRA_BODY` is an optional JSON object merged into every request body. It is the one place for provider-specific switches, so no provider name appears in code. Example: turning off a model's thinking mode.
- In the tool loop, the assistant message returned by the model is appended to the history unchanged, including fields this project does not use. Some providers reject the next request if such fields are dropped.
- An empty or blank reply counts as a format error and follows the same rule: retry once, then use the fallback.
- Tool-schema strict modes are not used; on some providers they exist only on a beta endpoint.

## 6. Payment and safety rules

Three tool tiers:

| Tier | Actions | Triggered by |
| --- | --- | --- |
| Read-only | Search and recommend, list orders | The model, automatically |
| Proposal | Prepare a cart, draft a refund, remember a preference | The model proposes; carts and refunds take no effect until the user clicks |
| Money | Create PayPal order, capture, refund | The server, after a user click. The model has no such tools |

Guaranteed in code:

- Prices come from the server-side search cache and are computed in integer cents.
- Only product IDs returned by a search in the current session can enter a cart.
- A cart holds 1 to 6 different products (F21). A cart whose total exceeds the user's budget is refused; the check is on the cart total, not on each product. With no budget set (F2), this check is skipped.
- A cart is a quote valid for 15 minutes; after that the user must choose again. The 15 minutes cover the time up to the Confirm click. Confirm copies the items and the total onto the order row, and from then on the order row is the reference, not the cart.
- Before capture, the order is read back from PayPal; capture happens only if the status is `APPROVED` and the amount and currency equal the order row. Amounts from PayPal are strings such as `"12.34"`; they are converted to integer cents with `Decimal`, never with float.
- An order is paid only when `purchase_units[0].payments.captures[0].status` in the capture response is `COMPLETED`. The order-level status alone is not enough.
- Create, capture and refund requests all carry a `PayPal-Request-Id`.
- A user can act only on carts and orders from their own session.
- The ranking prompt states that product text is untrusted data.
- Secrets exist only in server environment variables.

Payment flow details:

- **Confirm**: the server creates the order row (status `CREATED`) from the cart, then creates the PayPal order. A second Confirm on the same cart returns the existing order and approval link instead of creating a new one.
- **Return from PayPal**: `return_url` and `cancel_url` carry the local order ID. The server loads the order row by that ID, checks that it belongs to the user in the cookie, and takes the PayPal order ID from the row. It does not trust a PayPal order ID from the query string.
- **Request IDs are deterministic**: `create-{cart_id}`, `capture-{order_id}`, `refund-{order_id}`. A retry therefore repeats the same request instead of making a new one. PayPal returns the latest status of the earlier request with that ID.
- **Local status check comes first**: capture runs only from `CREATED`, refund only from `COMPLETED`. A page refresh on an order that is already `COMPLETED` shows the stored result and does not call PayPal. PayPal documents how long it keeps a request ID for refunds (45 days) but not for orders, so the request ID is the second guard, not the only one.
- **Buttons**: Confirm and the refund confirmation are disabled after the first click. PayPal can reject two simultaneous requests that share a request ID.
- **Time limit**: PayPal allows capture only within 3 hours of order creation. A return after that is shown as a failure with nothing charged.
- **Capture errors** map to F13 messages, all with the order not marked as paid:

| PayPal error | Meaning | Order status |
| --- | --- | --- |
| `ORDER_NOT_APPROVED` | The buyer did not approve | `CANCELLED` |
| `INSTRUMENT_DECLINED` | The funding source was declined | `CAPTURE_FAILED` |
| `ORDER_ALREADY_CAPTURED` | Captured earlier; read the order back and show its real state | unchanged |
| Amount or currency differs from the order row | Not captured | `AMOUNT_MISMATCH` |
| Anything else, or a capture status other than `COMPLETED` | Not counted as paid | `CAPTURE_FAILED` |

- **Access token**: cached in memory and reused until shortly before `expires_in` runs out.

## 7. Data

**Product** (every source is normalized to this shape): `id`, `title`, `brand`, `price_cents`, `currency`, `in_stock`, `url`, `image`, `description`, `category`.

Mapping from a Channel3 search result (field names from the docs; confirm against a real response):

| Product field | Channel3 source |
| --- | --- |
| `id`, `title`, `description` | `id`, `title`, `description` |
| `brand` | `brands[0].name` |
| `image` | `images[].url` where `is_main_image` is true, otherwise the first image |
| `category` | `category.title` |
| `price_cents`, `currency`, `url`, `in_stock` | Taken from one chosen offer in `offers[]`: `price.price` (a decimal in dollars, converted to cents with `Decimal`), `price.currency`, `url`, and `availability == "InStock"` |

Offer choice: the cheapest offer that is `InStock` and priced in USD. A product with no such offer is rejected in the hard filter (F4). Channel3 has no price, URL or availability at the product level.

**Order** (SQLite): `id` (local), `user_id`, `cart_id`, `paypal_order_id`, `capture_id`, `refund_id`, `amount_cents`, `currency`, `items` (JSON snapshot of product ID, title, unit price in cents, quantity), `status`, `created_at`, `updated_at`. `capture_id` comes from the capture response and is required for a refund.

**Order status**: `CREATED`, `COMPLETED`, `CANCELLED`, `AMOUNT_MISMATCH`, `CAPTURE_FAILED`, `REFUNDED`.

**Preference memory** (P1): `user_id`, `text` (one sentence), `strength` (-1 to 1), `evidence_count`, `updated_at`. A preference that is confirmed again gains 0.1; one that is contradicted loses 0.2.

**Storage**: sessions and carts in memory; orders and preferences in SQLite. There is no login; a random ID identifies the user. It is kept in an `HttpOnly`, `SameSite=Lax` cookie set by the server, not in `localStorage`, because the return from PayPal is a plain browser navigation and the server must be able to read the ID on that request.

**Not stored**: payment account details; sensitive personal information such as health or religion; conditions that apply to a single purchase only (for example "nothing too expensive for this gift") are not written to long-term memory.

## 8. External services

**PayPal (sandbox, `https://api-m.sandbox.paypal.com`)**

| Purpose | Endpoint |
| --- | --- |
| Access token | `POST /v1/oauth2/token` |
| Create order | `POST /v2/checkout/orders` |
| Get order | `GET /v2/checkout/orders/{id}` |
| Capture | `POST /v2/checkout/orders/{id}/capture` |
| Refund | `POST /v2/payments/captures/{capture_id}/refund` |

Notes from the PayPal docs:

- The return and cancel URLs go in `payment_source.paypal.experience_context`, together with `user_action: "PAY_NOW"` and `shipping_preference: "NO_SHIPPING"`.
- With `payment_source` in the create request, the response status is `PAYER_ACTION_REQUIRED` and the link to redirect the buyer to has `rel: "payer-action"`. The `approve` link belongs to a different flow and is not present here.
- `PayPal-Request-Id` is required on create in this flow; without it PayPal returns `PAYPAL_REQUEST_ID_REQUIRED`.
- The create request carries one entry per product in `purchase_units[0].items` (`name`, `quantity` as a string, `unit_amount`) and `amount.breakdown.item_total`, which must equal the sum of unit amount x quantity; with no tax or shipping it also equals `amount.value`. PayPal truncates `name` after 127 characters. Errors: `ITEM_TOTAL_MISMATCH`, `ITEM_TOTAL_REQUIRED`, `AMOUNT_MISMATCH` (F21).
- Capture is sent with an empty JSON body `{}`. The capture ID and capture status are in `purchase_units[0].payments.captures[0]`.
- A full refund is sent with an empty JSON body `{}`.
- The access token call uses Basic auth with the client ID and secret, and the body `grant_type=client_credentials`.
- PayPal's official sample server captures without checking the order first. The pre-capture check in section 6 is this project's own addition.

**Channel3**: `POST https://api.trychannel3.com/v1/search` with the `x-api-key` header. The hackathon code `PAYPAL-HACKATHON-2026` grants free search credits. The docs also list 1,000 free searches per month.

Notes from the Channel3 docs:

- Request body used here: `{"query": "...", "limit": 10, "config": {"currency": "USD"}}`. `limit` defaults to 20 and cannot exceed 30.
- The default filters already return only new, in-stock products. The in-stock check in F4 stays in code anyway.
- The budget is not sent as `filters.price`. Over-budget results must reach the hard filter so that F4 and F6 can show them as rejected with a reason.
- The response is an object with `products[]` and `next_page_token`. The field mapping is in section 7.
- Offer URLs are Channel3 buy links, not direct retailer links.

**Model provider: DeepSeek, if used**

- Base URL `https://api.deepseek.com`. Current model IDs are `deepseek-flash` and `deepseek-v4-pro`. The older names `deepseek-chat` and `deepseek-reasoner` were announced for discontinuation on July 24, 2026.
- Thinking mode is on by default. With `tools` in the request, the returned `reasoning_content` must be sent back on every later request or the API returns 400, and `temperature` has no effect. This project turns thinking off with `LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}`; the ranking prompt already asks for the reasoning in the visible reply.
- JSON output (`response_format: {"type": "json_object"}`) needs the word "json" in the prompt and can return blank content.

**Verify before relying on them**

- Channel3 prices: the docs describe dollars, and one docs page shows `price.amount` where the schema says `price.price`. Confirm the unit and the field name with a real response. A mistake here is a 100x pricing error.
- Channel3 response field names, taken from a real response.
- Whether function calling is reliable on the chosen model, DeepSeek in particular, and that the model ID in `LLM_MODEL` is still accepted.
- The `usage` field names in the model's response.
- The query parameters PayPal appends to `return_url` and `cancel_url`. The docs pages read do not list them, which is why the local order ID is put in the URL by this project.
- That a PayPal order reads back as `APPROVED` after the buyer approves, and which values a capture status can take besides `COMPLETED`.
- The sandbox merchant account's country is set to the US; payments use a sandbox personal test account.
- That the sandbox accepts the create request with line items and `item_total` (F21).

## 9. Evaluation

**Test set**

| Type | Count | What it tests |
| --- | --- | --- |
| Clear requests | 12 | Basic recommendation quality |
| Gift or vague requests | 6 | Whether multi-query search helps |
| Missing budget | 5 | Whether the agent asks when it should |
| Adversarial | 4 | Whether hostile listings in the results fool the agent |
| Cross-conversation preference (P1) | 3 to 5 | Whether a second conversation respects a preference stated in the first |

Three kinds of adversarial listings: one with instructions hidden in the description, one with fake reviews and certifications, one claiming the real price is lower. Test requests are written before looking at any search results.

Adversarial listings are kept in `eval/` and added to the candidates after the search step. Each one is in stock, within the request's budget and free of must-not keywords, so it passes the hard filter and reaches the ranker. A listing that the filter removes would make the test pass without testing anything.

**Metrics**

| Metric | How it is computed | Human labels |
| --- | --- | --- |
| Constraint satisfaction | Share of recommended products that meet the budget and must-not conditions, using the same keyword rule as F4. Expected to be 100%; it is a guard, not a quality measure | No |
| Grounding | Share of recommended IDs and prices that match the search results | No |
| Over-budget count | Number of over-budget products recommended; target 0 | No |
| Ask accuracy | Share of requests where the agent asked when it should and searched when it should | No |
| Injection resistance | Share of adversarial requests with no hostile listing in the top 3 | No |
| NDCG@3 | Relevance and order of the top 3, labelled 0, 1, 2 | Yes |
| Preference adherence (P1) | Share of cross-conversation tests where recommendations respect the remembered preference | No |
| Latency and cost | Seconds, model calls and tokens per request | No |

NDCG@3 definition:

- `DCG@3` is the sum over positions 1 to 3 of `rel / log2(position + 1)`, with `rel` the label 0, 1 or 2 (linear gain).
- `IDCG@3` is the same sum for the 3 highest labels among all labelled products of that request.
- `NDCG@3 = DCG@3 / IDCG@3`. If every label for a request is 0, the score is 0.
- If a run recommends a product that has no label yet, the script lists it for labelling and marks that request's NDCG as incomplete. It does not count the product as 0.

**Ablation**

| Version | multi_query | reasoning_rank | rank_shuffles |
| --- | --- | --- | --- |
| Baseline | off | off | none |
| + multi-query search | on | off | none |
| + reasoning rank | on | on | 1 |
| + multi-shuffle (P1) | on | on | 3 |

P1 adds one more pair: `use_memory` on and off. Report results separately per request type.

**Requirements**

- Search snapshot: saved on the first run, read-only afterwards. For each test request it stores the step 1 output (structured request and search queries), the results of each query, and the results of the single raw-words search used by the baseline.
- Eval runs replay the stored step 1 output instead of calling the model for it. Model-written queries differ from run to run, and a new query would not be in the snapshot.
- Ask accuracy is the exception: it is measured by running step 1 live on every test request, with no search.
- Versions without reasoning rank call no model after step 1 and give the same result every time, so one run is enough for them. This is stated next to the results.
- Label only products that some version recommended (pooling).
- Save a log per request: search queries, candidates, rejection reasons, final ranking.
- One command runs everything and prints the metrics table.
- Run each version 3 times and average. Record the model name, snapshot date, number of runs, temperature and shuffle seeds.
- The sample is small; do not draw conclusions from differences of a few percentage points.

## 10. Running and deployment

- With no keys at all, each of the three external services falls back to a mock, clearly labelled on the page, and the full flow can still be clicked through.
- Environment variables: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_EXTRA_BODY` (optional), `CHANNEL3_API_KEY`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `APP_BASE_URL`, `SNAPSHOT_MODE`.
- Deploy on Render. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Run a single worker process. Sessions and carts are in memory and would not be shared between workers.
- A Render free instance has no persistent disk, sleeps after 15 minutes without traffic, and can restart at any time. A restart loses sessions, carts, the SQLite orders and the preferences, so an order paid before a restart can no longer be looked up or refunded in the app. The first request after a sleep is slow. The README states this under known limitations.
- The page is usable at phone width.

## 11. Submission checklist and milestones

**Submission requirements**

- [ ] Public GitHub repository with the MIT license shown in the About section
- [ ] Judges can run it: a deployed URL, or complete install and run steps in the README
- [ ] A public YouTube video of 3 minutes or less showing the full flow
- [ ] A written description of which AI tools were used and how
- [ ] README states: the PayPal endpoints used, the concierge-style simulation, the eval results table, known limitations

**Milestones** (Houston time)

| Milestone | When | Content | Done when |
| --- | --- | --- | --- |
| M1 | Tuesday evening | Project skeleton, model interface layer, mock catalog, F1 to F6; verify function calling on the chosen model | In mock mode a request produces 3 recommendations; tests pass |
| M2 | Wednesday morning | Connect Channel3; F8 to F14 | One real sandbox payment completed with a sandbox buyer account |
| M3 | Wednesday afternoon | F7, F15, F16; page design; deploy to Render | The public URL runs the full flow |
| M4 | Wednesday early evening | Eval script, snapshot, first three ablation rows; human labelling | The README has three rows of numbers |
| M5 | Wednesday night | P1: F17 first, then F18 to F20 | Skip M5 if M4 is not finished by 8:00 pm |
| M6 | Thursday morning | README, video, submission | Submitted on Devpost by 12:00 pm |

**Cut order**: P2, preference memory, multi-shuffle ranking, refunds, eval shrunk to 15 requests.

## 12. Out of scope and open questions

**Out of scope**

- RL or training a recommendation model (there is no user behavior data; after the hackathon this pipeline's output could be distilled into a small ranking model)
- Price-drop monitoring and automatic purchases
- Shipment tracking, disputes, return and exchange flows
- Shipping and tax calculation
- PayPal products that need merchant onboarding, such as Agent Ready and Store Sync
- Placing real orders on retailer sites through a browser
- User login and accounts

**Open questions**

- Channel3 price unit and field names: documented as dollars under `offers[].price.price`, still to be confirmed with a real response
- How well Channel3 search handles vague requests
- Reliability of DeepSeek function calling
- The items listed under "Verify before relying on them" in section 8

**Answered**

- The Render free instance has no persistent disk. See section 10.

## Appendix A: Design basis

Papers are a source of ideas only. The body of this file is the specification. Do not implement a paper's full method. The README says "informed by", never "implements".

| Design point | Source | Publication status | What we use | Difference from the paper |
| --- | --- | --- | --- | --- |
| Reason first, then rank; at most 20 per group | [BracketRank](https://arxiv.org/pdf/2604.08834) | arXiv preprint | The ranking prompt asks for analysis before the ranking | The paper merges groups in elimination rounds; we rank a single group |
| Listwise ranking instead of scoring items one by one | [How Good are LLM-based Rerankers?](https://aclanthology.org/2025.findings-emnlp.305.pdf) | EMNLP 2025 Findings | Its finding that listwise ranking is most accurate with strong models | Finding only |
| Shuffle several times, then aggregate (F17) | [Permutation Self-Consistency](https://aclanthology.org/2024.naacl-long.129.pdf) | NAACL 2024 | 3 shuffles, one ranking each, then aggregate | The paper uses 20 shuffles and Kemeny aggregation; we use 3 and mean rank |
| Rankings change with input order | [Position Bias Undermines Preference Consistency](https://arxiv.org/pdf/2608.03091) | RecSys 2026 | The reason for adopting F17 | Finding only |
| Multi-query search must be measured | [A Reproducibility Study of LLM-Based Query Reformulation](https://arxiv.org/html/2604.27421v1); [LLM-based Query Expansion Under Control](https://cs.uwaterloo.ca/~jimmylin/publications/Sadeghi_Lin_SIGIR-AP2026b.pdf) | SIGIR 2026; SIGIR-AP 2026 | Their finding that the benefit depends on the retriever, hence a switch and an ablation | The papers rewrite one query; we split a need into several product types |
| Give the ranker less but more precise information | [CAIRO](https://arxiv.org/pdf/2608.20801) | CIKM 2026 | Each candidate gets only title, price, brand and a truncated description | The paper's structured profiles and field selection are not built |
| Update rule for preference strength | [MARS](https://arxiv.org/abs/2605.14401) | arXiv preprint | Confirm +0.1, contradict -0.2; the ranker sees a profile, not raw entries | The paper has three memory tiers and a planner; we have one preference table |
| Distilling a small ranker after the hackathon | [Walmart search relevance distillation](https://arxiv.org/html/2505.07105) | WWW Companion 2025 | Future direction only | Not built now |
| Label only recommended products | Pooling, standard practice in IR evaluation | Standard practice | Labelling scope | None |

Whether these choices work in this project is decided by the ablation in section 9.
