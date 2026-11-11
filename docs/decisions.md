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
