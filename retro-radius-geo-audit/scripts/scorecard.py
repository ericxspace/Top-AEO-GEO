#!/usr/bin/env python3
"""scorecard.py: roll one scan into a dated scorecard and diff it against the previous scan.

Inputs live in one scan folder (default 18-aeo-geo/geo-scans/<YYYY-MM-DD>/):
  bot_view.json           from bot_view.py --out
  passages/*.json         from passage_lint.py --out (one per page)
  entity.json             filled by hand from references/entity-template.json (optional)
Writes scorecard.json + scorecard.md into the same folder.

Deliberately NO blended composite score (geo-seo-claude's 25/20/20/15/10/10 weights are, in its own
docs, "not derived from a controlled study"). Each sub-score is reported on its own next to the
ground truth (AI-referred sessions from PostHog, entered in entity.json), and the delta is per
sub-score. RR rule: first-party data beats generic weights.

  python scorecard.py --scan-dir "18-aeo-geo/geo-scans/2026-10-14"
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rrgeo_common import load_json  # noqa: E402

PENALTY = {"critical": 30, "high": 15, "medium": 8, "low": 2, "info": 0}


def access_score(bv):
    s = 100
    per_bot = bv["robots"]["per_bot"]
    s -= 15 * sum(1 for b in per_bot.values() if b["tier"] == 1 and b["blocked_paths"])
    # only bot-specific blocks count; 429 = our own scan rate, page-wide 404 = a missing page (truth score)
    bad_bots = {f["msg"].split()[0] for f in bv["flags"] if f["code"] == "bot-non-200"}
    s -= 10 * len(bad_bots)
    if bv["robots"]["status"] != 200:
        s -= 20
    return max(s, 0)


def machine_truth_score(bv):
    """One penalty per distinct issue, scaled by the share of sampled pages it touches.
    (v1.0 charged every page separately, so one sitewide cart-drawer string on 39 pages zeroed the score.)"""
    access_codes = {"robots-blocks-bot", "bot-non-200", "robots-unreachable", "rate-limited"}
    n_pages = max(len(bv["pages"]), 1)
    by_code = {}
    for f in bv["flags"]:
        if f["code"] in access_codes:
            continue
        sev, pages = by_code.get(f["code"], (f["severity"], set()))
        pages.add(f["page"])
        if PENALTY.get(f["severity"], 0) > PENALTY.get(sev, 0):
            sev = f["severity"]
        by_code[f["code"]] = (sev, pages)
    s = 100.0
    for sev, pages in by_code.values():
        s -= PENALTY.get(sev, 0) * (0.5 + 0.5 * min(len(pages) / n_pages, 1))
    return max(round(s), 0)


def entity_score(e):
    if not e:
        return None
    pts = 0
    n = len(e.get("organization_sameAs") or [])
    pts += 20 if n >= 5 else 12 if n >= 3 else 6 if n >= 1 else 0
    prof = e.get("profiles") or []
    if prof:
        pts += round(20 * sum(1 for p in prof if p.get("definition_consistent")) / len(prof))
    m = e.get("independent_mentions", 0)
    pts += 25 if m >= 10 else 15 if m >= 5 else 8 if m >= 1 else 0
    r = e.get("reddit_threads_mentioning", 0)
    pts += 15 if r >= 5 else 8 if r >= 1 else 0
    pts += 10 if e.get("youtube_third_party", 0) >= 1 else 0
    b = e.get("branded_prompts") or {}
    if b.get("total"):
        pts += round(10 * b.get("recognised", 0) / b["total"])
    return min(pts, 100)


def build(scan_dir):
    bv_path = os.path.join(scan_dir, "bot_view.json")
    bv = load_json(bv_path) if os.path.exists(bv_path) else None
    passages = [load_json(p) for p in sorted(glob.glob(os.path.join(scan_dir, "passages", "*.json")))]
    ent_path = os.path.join(scan_dir, "entity.json")
    ent = load_json(ent_path) if os.path.exists(ent_path) else None
    scored = [p for p in passages if p.get("score") is not None]
    card = {
        "scan": os.path.basename(os.path.normpath(scan_dir)),
        "subscores": {
            "access": access_score(bv) if bv else None,
            "machine_truth_parity": machine_truth_score(bv) if bv else None,
            "passage_citability": round(sum(p["score"] for p in scored) / len(scored), 1) if scored else None,
            "entity_footprint": entity_score(ent),
        },
        "ground_truth": (ent or {}).get("ground_truth"),
        "flag_counts": bv["flag_counts"] if bv else None,
        "ship_blocked_pages": [p["src"] for p in passages if p.get("ship_blocked")],
        "passages": [{"src": p["src"], "type": p["type"], "score": p.get("score"),
                      "misses": [c["code"] for c in p.get("checks", []) if not c["pass"]],
                      "gates": [f"{g['level']}:{g['code']}" for g in p.get("gates", [])]} for p in passages],
        "top_flags": [f for f in (bv["flags"] if bv else []) if f["severity"] in ("critical", "high", "medium")][:25],
    }
    return card


def previous(scan_dir):
    root = os.path.dirname(os.path.normpath(scan_dir))
    me = os.path.basename(os.path.normpath(scan_dir))
    older = sorted(d for d in os.listdir(root)
                   if d < me and os.path.exists(os.path.join(root, d, "scorecard.json")))
    return load_json(os.path.join(root, older[-1], "scorecard.json")) if older else None


def fmt_delta(cur, prev):
    if cur is None or prev is None:
        return "n/a"
    d = round(cur - prev, 1)
    return f"{'+' if d > 0 else ''}{d}" if d else "0"


def to_md(card, prev):
    L = [f"# GEO scan {card['scan']}", "",
         "Diagnostic sub-scores (0-100, no blended composite). Ground truth = AI-referred sessions.", "",
         "| Sub-score | This scan | Previous | Delta |", "|---|---|---|---|"]
    for k, v in card["subscores"].items():
        pv = (prev or {}).get("subscores", {}).get(k)
        L.append(f"| {k} | {v if v is not None else 'n/a'} | {pv if pv is not None else 'n/a'} | {fmt_delta(v, pv)} |")
    gt = card.get("ground_truth")
    if gt:
        L += ["", f"**Ground truth:** {json.dumps(gt)}"]
    if card["ship_blocked_pages"]:
        L += ["", "**Ship-blocked pages (gate FAIL):** " + ", ".join(card["ship_blocked_pages"])]
    L += ["", "## Pages linted", "", "| Page | Type | Score | Misses | Gates |", "|---|---|---|---|---|"]
    for p in card["passages"]:
        L.append(f"| {p['src']} | {p['type']} | {p['score']} | {', '.join(p['misses']) or '-'} | {', '.join(p['gates']) or '-'} |")
    L += ["", "## Flags (critical/high/medium)", ""]
    for f in card["top_flags"]:
        L.append(f"- **{f['severity']}** `{f['code']}` {f['msg']} ({f['page']})")
    if prev:
        old = {(f["code"], f["page"]) for f in prev.get("top_flags", [])}
        new = {(f["code"], f["page"]) for f in card["top_flags"]}
        L += ["", "## Changes since previous scan", "",
              f"- resolved: {len(old - new)}  " + "; ".join(f"{c} @ {p}" for c, p in sorted(old - new))[:1500],
              f"- new: {len(new - old)}  " + "; ".join(f"{c} @ {p}" for c, p in sorted(new - old))[:1500]]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan-dir", required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    card = build(a.scan_dir)
    prev = previous(a.scan_dir)
    with open(os.path.join(a.scan_dir, "scorecard.json"), "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2, ensure_ascii=True)
    md = to_md(card, prev)
    with open(os.path.join(a.scan_dir, "scorecard.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)


if __name__ == "__main__":
    main()
