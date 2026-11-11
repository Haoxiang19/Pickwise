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
