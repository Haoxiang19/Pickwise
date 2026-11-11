# Eval

```bash
python -m eval.run_eval --name full
```

## Files

| File | What it is |
| --- | --- |
| `requests.json` | 31 test requests: 12 clear, 6 gift/vague, 5 missing budget, 4 adversarial, 4 cross-conversation preference (`first` = conversation 1, `text` = conversation 2, `check` = keyword the top pick should contain). Written before looking at any search results. |
| `adversarial.json` | 3 hostile listings per adversarial request (hidden instructions, fake reviews/certifications, fake "real price"). Injected in front of the search results; the runner refuses a listing that the hard filter would remove. |
| `labels.json` | Human relevance labels, `{"<request id>": {"<product id>": 0, 1 or 2}}`. Empty until labelled by hand. |
| `snapshot.json` | Created on the first run with a real model **and** a real catalog key: step 1 output and search results per request (and, for preference tests, the profile saved by conversation 1). Existing entries are never changed; a new test request gets its own dated entry. |
| `snapshot_mock.json` | Same, built when any service is mocked. Git-ignored; its numbers are not results. |
| `runs/<name>/` | `logs.jsonl` (per request: queries, candidates, rejection reasons, ranking, recommendations), `summary.json`, `to_label.json`. Git-ignored. |

## What the runner does

1. Ask accuracy: step 1 live on all 31 requests, no search.
2. Ablation versions replay the snapshot: baseline (one raw-words search, search order), + multi-query search, + reasoning rank, + multi-shuffle (3 shuffles), and + memory (reasoning rank with memory on, preference requests only; compare with the + reasoning rank preference row). Versions without reasoning rank call no model, so they run once; the others run 3 times with seeds 101, 202, 303, and metrics are averaged over runs.
3. Prints one row per version and request type. The header records the models, catalog, snapshot date, runs, temperature and seeds.

## Labelling

After a run, `runs/<name>/to_label.json` lists every recommended product without a label (pooling across versions). Copy each product ID into `labels.json` under its request ID with a label: 0 = not relevant, 1 = acceptable, 2 = good fit. Run again: NDCG@3 is reported for requests whose top 3 are all labelled; the `unlabeled` column counts the rest.

## Notes

- Injection resistance for versions without reasoning rank reflects only where the hostile listings were placed (first), not robustness.
- Latency and cost columns cover steps 2-5 (one ranking call per request when reasoning rank is on). Step 1 cost is in `summary.json` under `ask.usage`.
- The sample is small: do not read differences of a few percentage points as real.
