#!/usr/bin/env python3
"""Reads an ads export, applies the rules in rules.json, writes a report of what it WOULD do.

It never changes an ad account. It writes proposed actions to actions.json and a
readable report. Something else (a connector, or you) applies them after you agree.
"""
import argparse, csv, json, os, sys
from collections import defaultdict
from datetime import date, timedelta


def load(path):
    with open(path, newline="") as f:
        return [{**r, "date": date.fromisoformat(r["date"]), "spend": float(r["spend"]),
                 "purchases": int(r["purchases"]), "adset_daily_budget": float(r["adset_daily_budget"])}
                for r in csv.DictReader(f)]


def cpa(spend, buys):
    return spend / buys if buys else None


def ad_stats(rows, as_of, rules):
    start = as_of - timedelta(days=rules["window_days"] - 1)
    stats = {}
    for r in rows:
        if r["date"] > as_of:
            continue
        s = stats.setdefault(r["ad_id"], {"ad_id": r["ad_id"], "name": r["ad_name"], "adset": r["adset_id"],
                                          "first": r["date"], "spend": 0.0, "purchases": 0})
        s["first"] = min(s["first"], r["date"])
        if r["date"] >= start:
            s["spend"] += r["spend"]
            s["purchases"] += r["purchases"]
    for s in stats.values():
        s["days_live"] = (as_of - s["first"]).days + 1
        s["cpa"] = cpa(s["spend"], s["purchases"])
    return stats


def propose_pauses(stats, rules):
    target, actions, held = rules["target_cpa"], [], []
    for s in stats.values():
        rule = None
        if s["purchases"] == 0 and s["spend"] >= rules["pause_zero_purchase_spend_multiple"] * target:
            rule = f'spent {s["spend"]:.0f} with no purchase (limit {rules["pause_zero_purchase_spend_multiple"]:g}x target CPA = {rules["pause_zero_purchase_spend_multiple"] * target:.0f})'
        elif s["purchases"] >= rules["pause_min_purchases"] and s["cpa"] > rules["pause_cpa_multiple"] * target:
            rule = f'CPA {s["cpa"]:.0f} is above {rules["pause_cpa_multiple"]:g}x target ({rules["pause_cpa_multiple"] * target:.0f}) over {s["purchases"]} purchases'
        if not rule:
            continue
        if s["days_live"] < rules["min_days_live"]:
            held.append({"ad_id": s["ad_id"], "name": s["name"], "why": f'would pause ({rule}) but live only {s["days_live"]} day(s); minimum {rules["min_days_live"]}'})
            continue
        actions.append({"action": "pause_ad", "status": "proposed", "ad_id": s["ad_id"], "name": s["name"],
                        "reason": rule, "spend": round(s["spend"], 2), "purchases": s["purchases"]})
    return actions, held


def propose_raises(rows, as_of, rules):
    n, target = rules["budget_raise_streak_days"], rules["target_cpa"]
    by_set = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    budget = {}
    for r in rows:
        by_set[r["adset_id"]][r["date"]][0] += r["spend"]
        by_set[r["adset_id"]][r["date"]][1] += r["purchases"]
        budget[r["adset_id"]] = r["adset_daily_budget"]
    candidates = []
    for aset, days in by_set.items():
        recent = [as_of - timedelta(days=i) for i in range(n)]
        daily = [cpa(*days[d]) if d in days else None for d in recent]
        if all(c is not None and c < target for c in daily):
            candidates.append((sum(daily) / n, aset))
    candidates.sort()
    committed, actions, blocked = sum(budget.values()), [], []
    for avg, aset in candidates:
        new = budget[aset] * (1 + rules["budget_raise_pct"] / 100)
        if committed - budget[aset] + new > rules["daily_spend_cap"]:
            blocked.append({"adset": aset, "why": f'raising {budget[aset]:.0f} to {new:.0f} would take total daily budget to {committed - budget[aset] + new:.0f}, over the cap of {rules["daily_spend_cap"]:.0f}'})
            continue
        committed += new - budget[aset]
        actions.append({"action": "raise_budget", "status": "proposed", "adset": aset, "from": budget[aset],
                        "to": round(new, 2), "reason": f'CPA under target ({target:g}) for {n} days in a row, average {avg:.1f}'})
    return actions, blocked


def propose_drafts(stats, rules):
    ok = [s for s in stats.values() if s["purchases"] >= rules["pause_min_purchases"] and s["cpa"] is not None]
    if not ok:
        return []
    best = min(ok, key=lambda s: s["cpa"])
    return [{"action": "draft_variants", "status": "proposed", "from_ad": best["ad_id"], "name": best["name"],
             "count": rules["draft_variants"], "create_paused": True,
             "reason": f'lowest CPA ({best["cpa"]:.1f}) over {best["purchases"]} purchases. Vary hook, first frame and call to action. This is a request, not a creative.'}]


def run(rows, rules, as_of):
    stats = ad_stats(rows, as_of, rules)
    pauses, held = propose_pauses(stats, rules)
    raises, blocked = propose_raises(rows, as_of, rules)
    return {"as_of": as_of.isoformat(), "mode": "report-only", "actions": pauses + raises + propose_drafts(stats, rules),
            "held": held, "blocked": blocked, "ads": sorted(stats.values(), key=lambda s: (s["cpa"] is None, s["cpa"]))}


def report(res, rules):
    L = [f'# Ad agent report, {res["as_of"]}', "", "Mode: **report-only**. Nothing was changed in any ad account.", "",
         f'Rules: target CPA {rules["target_cpa"]:g}, window {rules["window_days"]} days, daily cap {rules["daily_spend_cap"]:g}.', "",
         "## Ads in the window", "", "| Ad | Spend | Purchases | CPA | Days live |", "|---|---|---|---|---|"]
    for s in res["ads"]:
        L.append(f'| {s["name"]} | {s["spend"]:.0f} | {s["purchases"]} | {"none" if s["cpa"] is None else f"{s["cpa"]:.1f}"} | {s["days_live"]} |')
    L += ["", "## What it would do", ""]
    L += [f'- **{a["action"]}** {a.get("name") or a.get("adset") or ""}: {a["reason"]}' for a in res["actions"]] or ["- Nothing."]
    if res["held"]:
        L += ["", "## Held back", ""] + [f'- {h["name"]}: {h["why"]}' for h in res["held"]]
    if res["blocked"]:
        L += ["", "## Blocked by the spend cap", ""] + [f'- Ad set {b["adset"]}: {b["why"]}' for b in res["blocked"]]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("export")
    ap.add_argument("--rules", default="rules.json")
    ap.add_argument("--as-of", required=True, help="last day of data, YYYY-MM-DD")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args(argv)
    rules = json.load(open(a.rules))
    res = run(load(a.export), rules, date.fromisoformat(a.as_of))
    os.makedirs(a.out, exist_ok=True)
    open(f"{a.out}/{a.as_of}.md", "w").write(report(res, rules))
    json.dump({"as_of": res["as_of"], "mode": res["mode"], "actions": res["actions"]}, open(f"{a.out}/{a.as_of}.actions.json", "w"), indent=1)
    print(f'{len(res["actions"])} proposed actions, {len(res["held"])} held, {len(res["blocked"])} blocked -> {a.out}/{a.as_of}.md')


if __name__ == "__main__":
    sys.exit(main())
