# ad-pause-agent

The rules layer of an ad agent that pauses what loses money. It reads an ads export, applies rules you write in `rules.json`, and writes down what it **would** do and why. It never touches an ad account.

That is the point. An agent that spends money starts in report-only mode. You read its calls for a week. When you agree with them, you let something apply them.

## Run it

```sh
python3 pause_agent.py data/ads-export.csv --as-of 2026-11-14
```

No dependencies. Python 3.9+. Writes `reports/2026-11-14.md` (the readable report) and `reports/2026-11-14.actions.json` (the proposed actions, every one marked `"status": "proposed"`). Both are committed.

Tests: `python3 -m unittest -q tests/test_pause_agent.py`

## The rules (`rules.json`)

| Rule | Default |
|---|---|
| Pause an ad whose CPA is above a multiple of target, once it has enough purchases | above 3x target, 10+ purchases in the window |
| Pause an ad that spent a multiple of target CPA with zero purchases | 2x target |
| Never pause an ad that has been live fewer than N days (listed as "held back") | 3 days |
| Raise an ad set's budget when its CPA beat target N days in a row | +20% after 3 days |
| Never let total daily budget pass a cap (listed as "blocked") | 1,000 |
| Ask for new versions of the lowest-CPA ad, created paused | 3 variants |

Every number is yours to change. Every action in the report carries the numbers behind it.

## The sample run

`data/ads-export.csv` is **synthetic**: 14 days of daily spend and purchases for six made-up ads, generated with a fixed seed so the run is reproducible. It is not data from a real account. It is built so that every rule fires once, and the unit tests cover the edges: exactly at the limit, too few purchases, too new, over the cap.

## What it does not do

- **It does not connect to Meta, Google or anything else.** There is no live-account code here, and I have not run it on a live account. Export your ads as CSV with these columns: `date, ad_id, ad_name, adset_id, spend, purchases, adset_daily_budget`.
- **It does not apply actions.** Applying `actions.json` is a separate step you control, for example through Meta's official ads connector, which starts new ads paused.
- **It does not write creative.** `draft_variants` is a request that names the ad to vary, not a finished ad.
- Meta's learning phase needs roughly 50 results in a week and big edits can restart it. Keep raises small and keep the cap.

MIT licence.
