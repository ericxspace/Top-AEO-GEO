#!/usr/bin/env python3
"""bot_view.py: what AI crawlers actually receive from retroradius.com.

Read-only. For a sample of storefront URLs it checks:
  1. robots.txt per AI bot (longest-match Allow/Disallow), Content-Signal, Cloudflare-managed block,
     sitemap + agent pointers (agents.md / UCP)
  2. /llms.txt status + whether it is Shopify's agent-commerce file or a content map
  3. homepage HTTP layer: RFC 8288 Link rels, served theme id, Markdown negotiation
     (strict 'Accept: text/markdown' vs a realistic fallback header; verifies the BODY, not just the
     Content-Type, because Shopify labels HTML as text/markdown on the homepage)
  4. every URL x every bot UA: HTTP status + bytes (a CDN/WAF block shows up here, not in robots.txt)
  5. the raw HTML one bot receives (no JavaScript executed): JSON-LD types, Organization sameAs,
     aggregateRating, Offer shipping/return schema checked against references/truth-gate.json,
     speed-claim and Google-feed-wordlist regressions, page-type content markers.

Usage:
  python bot_view.py [--base https://retroradius.com] [--urls URL ...] [--urls-file F]
                     [--products 3] [--bots tier1|all|GPTBot,ClaudeBot] [--delay 0.3]
                     [--truth ../references/truth-gate.json] [--out bot_view.json]

Caveat printed in the output: user-agent spoofing from a non-bot IP. A CDN that verifies bots by
IP/reverse-DNS can treat a spoof differently from the real crawler, so a 200 here is strong but not
absolute evidence; a 403 here must be confirmed in Bing Webmaster Tools / GSC crawl stats before acting.
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rrgeo_common import (BROWSER_UA, canonical, dump, fetch, find_all, first, iter_typed,  # noqa: E402
                          jsonld_blocks, load_json, meta_content, parse_html, served_theme_id,
                          text_of, types_of, words)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TRUTH = os.path.normpath(os.path.join(HERE, "..", "references", "truth-gate.json"))

# token: (tier, purpose, fetch UA or None when the token is robots.txt-only)
BOTS = {
    "GPTBot": (1, "OpenAI crawl (training + search corpus)",
               "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)"),
    "OAI-SearchBot": (1, "ChatGPT search index",
                      "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"),
    "ChatGPT-User": (1, "ChatGPT live fetch for a user",
                     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot"),
    "ClaudeBot": (1, "Anthropic crawl",
                  "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"),
    "Claude-SearchBot": (1, "Claude search index",
                         "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-SearchBot/1.0; +https://www.anthropic.com)"),
    "Claude-User": (1, "Claude live fetch for a user",
                    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)"),
    "PerplexityBot": (1, "Perplexity index",
                      "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)"),
    "Perplexity-User": (1, "Perplexity live fetch for a user",
                        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)"),
    "bingbot": (1, "Bing index = ChatGPT/Copilot grounding",
                "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/128.0 Safari/537.36"),
    "Googlebot": (1, "Google index = AI Overviews / AI Mode",
                  "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
    "Google-Extended": (2, "robots token: Gemini training/grounding opt-out (no own UA)", None),
    "Applebot": (2, "Siri/Spotlight + Apple Intelligence fetch",
                 "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1.1 Safari/605.1.15 (Applebot/0.1; +http://www.apple.com/go/applebot)"),
    "Applebot-Extended": (2, "robots token: Apple model training opt-out (no own UA)", None),
    "meta-externalagent": (2, "Meta AI crawl",
                           "meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)"),
    "Amazonbot": (2, "Alexa / Rufus",
                  "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot) Chrome/119.0 Safari/537.36"),
    "DuckAssistBot": (2, "DuckDuckGo AI answers", "DuckAssistBot/1.2; (+http://duckduckgo.com/duckassistbot.html)"),
    "MistralAI-User": (2, "Le Chat live fetch",
                       "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; MistralAI-User/1.0; +https://docs.mistral.ai/robots)"),
    "CCBot": (3, "Common Crawl (training only)", "CCBot/2.0 (https://commoncrawl.org/faq/)"),
    "Bytespider": (3, "ByteDance (training)", "Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; Bytespider; spider-feedback@bytedance.com)"),
}
CRITICAL_BOTS = {"OAI-SearchBot", "ChatGPT-User", "bingbot", "Googlebot", "PerplexityBot", "Claude-SearchBot"}
ROBOTS_TEST_PATHS = ["/", "/products/x", "/collections/x", "/blogs/x/y", "/pages/x", "/policies/shipping-policy"]
KNOWN_SIGNAL_KEYS = {"search", "ai-input", "ai-train"}


# ---------------------------------------------------------------- robots.txt

def parse_robots(text):
    groups, cur, last_agent = [], None, False
    signals, sitemaps = [], []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            if cur is None or not last_agent:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(v.lower())
            last_agent = True
            continue
        last_agent = False
        if k in ("allow", "disallow") and cur is not None:
            cur["rules"].append((k, v))
        elif k == "content-signal":
            signals.append({"agents": cur["agents"] if cur else ["*"], "value": v})
        elif k == "sitemap":
            sitemaps.append(v)
    return groups, signals, sitemaps


def _match_len(pattern, path):
    if not pattern:
        return -1
    rx = re.escape(pattern).replace(r"\*", ".*")
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return len(pattern) if re.match(rx, path) else -1


def robots_verdict(groups, token, path):
    tok = token.lower()
    rules = [r for g in groups if tok in g["agents"] for r in g["rules"]]
    group = token
    if not any(tok in g["agents"] for g in groups):
        rules = [r for g in groups if "*" in g["agents"] for r in g["rules"]]
        group = "*"
    best_len, allowed = -1, True
    for kind, pat in rules:
        n = _match_len(pat, path)
        if n > best_len or (n == best_len and kind == "allow"):
            best_len, allowed = n, (kind == "allow")
    return allowed, group


# ---------------------------------------------------------------- sampling

def sitemap_locs(url, delay):
    r = fetch(url)
    time.sleep(delay)
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r["body"]) if r["status"] == 200 else []


def default_sample(base, n_products, delay):
    urls = [base + "/"]
    index = sitemap_locs(base + "/sitemap.xml", delay)
    by_kind = {"products": [], "collections": [], "articles": [], "blogs": []}
    for child in index:
        for kind in by_kind:
            if f"sitemap_{kind}" in child:
                by_kind[kind] += [u for u in sitemap_locs(child, delay)
                                  if u.rstrip("/") != base.rstrip("/")]
    urls += by_kind["products"][:n_products]
    urls += [u for u in by_kind["collections"] if "/collections/all" not in u][:2]
    # Shopify lists articles in sitemap_articles_*; older stores put them under sitemap_blogs_*
    urls += [u for u in by_kind["articles"] + by_kind["blogs"] if u.count("/") >= 5][:2]
    urls += [base + "/pages/about", base + "/policies/shipping-policy"]
    seen, out = set(), []
    for u in urls:
        u = u.replace("&amp;", "&")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def page_type(url):
    p = urlparse(url).path.rstrip("/")
    if p in ("", "/"):
        return "home"
    if "/products/" in p:
        return "product"
    if p.startswith("/collections/"):
        return "collection"
    if p.startswith("/blogs/"):
        return "article" if p.count("/") >= 3 else "blog"
    if p.startswith("/policies/"):
        return "policy"
    if p.startswith("/pages/"):
        return "page"
    return "other"


# ---------------------------------------------------------------- page analysis

def _qv(d, key):
    v = d.get(key) if isinstance(d, dict) else None
    if isinstance(v, dict):
        return v.get("minValue"), v.get("maxValue"), v.get("unitCode")
    return None, None, None


def analyse_page(url, html, truth):
    root = parse_html(html)
    ptype = page_type(url)
    flags = []

    def flag(sev, code, msg):
        flags.append({"severity": sev, "code": code, "page": url, "msg": msg})

    title_node = first(root, "title")
    title = text_of(title_node) if title_node else ""
    meta_desc = meta_content(root, name="description")
    robots_meta = meta_content(root, name="robots")
    h1s = [text_of(h) for h in find_all(root, "h1")]
    h2s = [text_of(h) for h in find_all(root, "h2")]
    body = first(root, "body") or root
    visible = text_of(body)
    objs, ld_errors = jsonld_blocks(root)
    typed = [d for o in objs for d in iter_typed(o)]
    ld_types = sorted({t for d in typed for t in types_of(d)})

    info = {"type": ptype, "title": title, "meta_description": meta_desc, "canonical": canonical(root),
            "robots_meta": robots_meta, "h1": h1s, "h2_count": len(h2s),
            "question_h2": sum(1 for h in h2s if h.rstrip().endswith("?") or re.match(r"(how|what|why|which|can|do|does|is|are|should|where|when|will|who)\b", h.strip(), re.I)),
            "visible_words": len(words(visible)), "jsonld_types": ld_types,
            "jsonld_errors": ld_errors}

    if "noindex" in robots_meta.lower():
        flag("critical", "noindex", f"meta robots = '{robots_meta}'")
    if ld_errors:
        flag("medium", "jsonld-parse", f"{len(ld_errors)} JSON-LD block(s) do not parse: {ld_errors[0]}")
    if "Organization" not in ld_types and ptype in ("home", "product", "article"):
        flag("medium", "no-organization", "no Organization JSON-LD in raw HTML")

    orgs = [d for d in typed if "Organization" in types_of(d) and d.get("sameAs")]
    if orgs:
        same = orgs[0]["sameAs"]
        info["organization_sameAs"] = same if isinstance(same, list) else [same]

    # ---- Product / Offer truth checks
    if ptype == "product":
        prods = [d for d in typed if {"Product", "ProductGroup"} & set(types_of(d))]
        if not prods:
            flag("high", "no-product-schema", "no Product/ProductGroup JSON-LD in raw HTML")
        agg = [d.get("aggregateRating") for d in prods if isinstance(d.get("aggregateRating"), dict)]
        info["aggregateRating"] = ([{"ratingValue": a.get("ratingValue"), "reviewCount": a.get("reviewCount") or a.get("ratingCount")} for a in agg])
        if any(a.get("ratingValue") in (None, "", "null") for a in agg):
            flag("high", "rating-null", "aggregateRating present but ratingValue is empty (Liquid .rating vs .value trap)")
        info["review_nodes"] = sum(1 for d in typed if "Review" in types_of(d))
        info["has_gtin"] = any(any(k.startswith("gtin") for k in d) for d in prods)
        ships = [d for d in typed if "OfferShippingDetails" in types_of(d)]
        info["shipping_details"] = []
        tmin, tmax = truth["transit_business_days"]
        pmin, pmax = truth["processing_business_days"]
        for s in ships:
            dt = s.get("deliveryTime") or {}
            h = _qv(dt, "handlingTime")
            t = _qv(dt, "transitTime")
            rate = s.get("shippingRate") or {}
            dest = s.get("shippingDestination") or {}
            dests = dest if isinstance(dest, list) else [dest]
            countries = sorted({c for d in dests if isinstance(d, dict)
                                for c in ([d.get("addressCountry")] if isinstance(d.get("addressCountry"), str)
                                          else (d.get("addressCountry") or []))})
            row = {"handling": h, "transit": t, "rate": rate.get("value"), "countries": countries}
            info["shipping_details"].append(row)
            if (t[2] or h[2] or "").upper() in ("DAY", "D") and not dt.get("businessDays"):
                flag("medium", "schema-days-ambiguous",
                     f"deliveryTime in {t[2] or h[2]} with no businessDays: an engine can read transit "
                     f"{t[0]}-{t[1]} as calendar days (~1 week faster than the {tmin}-{tmax} business-day policy)")
            try:
                if t[1] is not None and float(t[1]) < tmin:
                    flag("critical", "schema-faster-than-policy",
                         f"OfferShippingDetails transit max {t[1]} {t[2] or ''} < policy {tmin}-{tmax} business days")
                if t[0] is None and t[1] is None:
                    flag("info", "schema-no-transit", "OfferShippingDetails has no transitTime: engines cannot read delivery speed from schema")
                if h[1] is not None and float(h[1]) < pmin:
                    flag("high", "schema-handling-short",
                         f"handlingTime max {h[1]} < policy processing {pmin}-{pmax} business days")
            except (TypeError, ValueError):
                pass
            if rate.get("value") not in (None, 0, "0", "0.0", "0.00") and truth.get("free_shipping"):
                flag("high", "schema-shipping-not-free", f"shippingRate {rate.get('value')} but policy = free US+CA")
            extra = [c for c in countries if c not in truth["markets"]]
            if extra:
                flag("medium", "schema-markets", f"shippingDestination includes {extra}; markets are {truth['markets']}")
        if prods and not ships:
            flag("medium", "no-shipping-schema", "no OfferShippingDetails: free US+CA shipping is invisible to engines")
        if prods and not any("MerchantReturnPolicy" in types_of(d) for d in typed):
            flag("medium", "no-return-schema", "no MerchantReturnPolicy in Product JSON-LD")
        # Google-feed wordlist on the synced fields (title tag = SEO title, H1 = product title, meta desc, handle)
        handle = urlparse(url).path.rstrip("/").split("/")[-1].replace("-", " ")
        fields = {"seo_title": title, "product_title_h1": " ".join(h1s[:1]),
                  "seo_description": meta_desc, "handle": handle}
        for term in truth["google_feed_wordlist"]["terms"]:
            rx = re.compile(r"\b" + re.escape(term) + r"\b", re.I)
            hit = [k for k, v in fields.items() if rx.search(v or "")]
            if hit:
                flag("high", "feed-wordlist", f"'{term}' in Google-synced field(s) {hit}")
        low = visible.lower()
        info["markers"] = {"common_questions": "common questions" in low,
                           "specifications": "specification" in low}
        if not info["markers"]["common_questions"]:
            flag("medium", "pdp-no-faq-text", "'Common Questions' block not in raw HTML (metafield not rendered?)")
        if not info["markers"]["specifications"]:
            flag("medium", "pdp-no-specs-text", "no 'Specifications' block in raw HTML")

    # ---- speed / delivery truth on every page type
    for pat in truth["speed_claim_patterns"]:
        m = re.search(pat, visible, re.I)
        if m:
            flag("high", "speed-claim", f"visible text claims speed: '{m.group(0)}' (Truth Gate)")
    est = re.search(truth["delivery_estimate_pattern"], visible)
    if est:
        has_policy = any(re.search(p, visible, re.I) for p in truth["policy_sentence_patterns"])
        info["delivery_estimate"] = est.group(0)
        info["delivery_duration_stated"] = has_policy
        if not has_policy:
            flag("medium", "estimate-without-policy",
                 f"date estimate '{est.group(0)}' is in raw HTML with no duration sentence "
                 "('15-18 business days' / '3-4 weeks'): an engine inferred 'fast shipping' from exactly this on 2026-10-01")

    if ptype == "article":
        info["has_dateModified"] = any(d.get("dateModified") for d in typed)
        info["faq_questions"] = sum(len(d.get("mainEntity") or []) for d in typed if "FAQPage" in types_of(d))
        info["updated_label"] = bool(re.search(r"\bUpdated\s+[A-Z][a-z]+\s+\d{4}", visible))
        if info["question_h2"] < 2:
            flag("medium", "article-few-question-h2", f"only {info['question_h2']} question-form H2s")
    if ptype == "collection":
        info["product_links"] = len({a.get("href").split("?")[0] for a in find_all(root, "a")
                                     if "/products/" in a.get("href")})
        if not meta_desc:
            flag("high", "collection-no-meta", "collection has no meta description")
    if ptype == "home":
        if "WebSite" not in ld_types:
            flag("low", "no-website-schema", "no WebSite JSON-LD on homepage")
    return info, flags


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="https://retroradius.com")
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--urls-file")
    ap.add_argument("--products", type=int, default=3, help="products taken from the sitemap when no --urls")
    ap.add_argument("--bots", default="tier1", help="tier1 | all | comma list of tokens")
    ap.add_argument("--analyse-as", default="OAI-SearchBot", help="bot whose raw HTML is parsed")
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--truth", default=DEFAULT_TRUTH)
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = a.base.rstrip("/")
    truth = load_json(a.truth)
    flags = []

    if a.bots == "tier1":
        fetch_bots = [k for k, v in BOTS.items() if v[0] == 1 and v[2]]
    elif a.bots == "all":
        fetch_bots = [k for k, v in BOTS.items() if v[2]]
    else:
        fetch_bots = [b.strip() for b in a.bots.split(",") if b.strip() in BOTS and BOTS[b.strip()][2]]

    # 1. robots.txt
    rb = fetch(base + "/robots.txt")
    groups, signals, sitemaps = parse_robots(rb["body"]) if rb["status"] == 200 else ([], [], [])
    robots = {"status": rb["status"], "cloudflare_managed": "cloudflare managed content" in rb["body"].lower(),
              "sitemaps": sitemaps, "content_signal": signals,
              "agent_pointers": sorted(set(re.findall(r"https?://\S+?(?:agents\.md|/\.well-known/ucp|/api/ucp/mcp)", rb["body"]))),
              "explicit_ai_groups": sorted({ag for g in groups for ag in g["agents"]
                                            if ag != "*" and ag in {k.lower() for k in BOTS}}),
              "per_bot": {}}
    if rb["status"] != 200:
        flags.append({"severity": "critical", "code": "robots-unreachable", "page": base + "/robots.txt",
                      "msg": f"robots.txt HTTP {rb['status']}"})
    for token, (tier, purpose, _ua) in BOTS.items():
        verdicts = {p: robots_verdict(groups, token, p) for p in ROBOTS_TEST_PATHS}
        blocked = [p for p, (ok, _g) in verdicts.items() if not ok]
        robots["per_bot"][token] = {"tier": tier, "purpose": purpose,
                                    "group": verdicts["/"][1], "blocked_paths": blocked}
        if blocked and tier == 1:
            flags.append({"severity": "critical" if token in CRITICAL_BOTS else "high", "code": "robots-blocks-bot",
                          "page": base + "/robots.txt", "msg": f"{token} blocked on {blocked}"})
    if robots["cloudflare_managed"]:
        flags.append({"severity": "high", "code": "cloudflare-managed-robots", "page": base + "/robots.txt",
                      "msg": "Cloudflare managed robots.txt block detected: check which AI bots it disallows"})
    if not signals:
        flags.append({"severity": "info", "code": "no-content-signal", "page": base + "/robots.txt",
                      "msg": "no Content-Signal directive (IETF draft, non-scoring). Shopify: only via robots.txt.liquid"})
    else:
        for s in signals:
            keys = {kv.split("=")[0].strip() for kv in s["value"].split(",") if "=" in kv}
            unknown = keys - KNOWN_SIGNAL_KEYS
            if unknown:
                flags.append({"severity": "info", "code": "content-signal-unknown-key", "page": base + "/robots.txt",
                              "msg": f"unknown Content-Signal keys {sorted(unknown)} (draft still moving)"})

    # 2. llms.txt
    lt = fetch(base + "/llms.txt")
    lbody = lt["body"] if lt["status"] == 200 else ""
    llms = {"status": lt["status"], "content_type": lt["headers"].get("content-type", ""),
            "first_line": lbody.strip().splitlines()[0][:120] if lbody.strip() else "",
            "kind": ("shopify-agent-instructions" if re.search(r"\bUCP\b|Agent Instructions", lbody)
                     else "content-map" if lbody else "absent"),
            "links": len(re.findall(r"\]\(https?://", lbody))}

    # 3. homepage HTTP layer
    hp = fetch(base + "/", ua=BROWSER_UA)
    link_rels = re.findall(r'rel="?([\w\- ]+)"?', hp["headers"].get("link", ""))
    md_tests = {}
    http_layer ={"served_theme_id": served_theme_id(hp["headers"]), "server": hp["headers"].get("server", ""),
                  "link_rels": sorted(set(r.strip() for r in link_rels)),
                  "ucp_link": "ucp" in [r.strip() for r in link_rels]}

    # sample
    urls = list(a.urls)
    if a.urls_file:
        with open(a.urls_file, encoding="utf-8") as f:
            urls += [l.strip() for l in f if l.strip() and not l.startswith("#")]
    if not urls:
        urls = default_sample(base, a.products, a.delay)
    neg_paths = ["/"] + sorted({urlparse(u).path for u in urls if page_type(u) in ("product", "collection")})[:2]
    for path in neg_paths:
        for label, accept in (("strict", "text/markdown"),
                              ("fallback", "text/markdown, text/html;q=0.9, */*;q=0.8")):
            r = fetch(base + path, accept=accept)
            time.sleep(a.delay)
            ct = r["headers"].get("content-type", "")
            looks_html = bool(re.search(r"<!doctype html|<html[\s>]", r["body"][:2000], re.I))
            verdict = ("404" if r["status"] == 404 else
                       "real-markdown" if "markdown" in ct and not looks_html else
                       "html-labelled-markdown" if "markdown" in ct and looks_html else
                       "html-fallback" if r["status"] == 200 else f"http-{r['status']}")
            md_tests[f"{label} {path}"] = {"status": r["status"], "content_type": ct, "verdict": verdict}
            if label == "fallback" and r["status"] != 200:
                flags.append({"severity": "high", "code": "md-fallback-breaks", "page": base + path,
                              "msg": f"Accept: text/markdown with HTML fallback returns {r['status']}"})
    http_layer["markdown_negotiation"] = md_tests
    if any(v["verdict"] == "404" for v in md_tests.values()):
        flags.append({"severity": "info", "code": "md-strict-404", "page": base,
                      "msg": "strict 'Accept: text/markdown' gets 404 on some templates (Shopify platform behaviour; "
                             "agents that send an HTML fallback are fine). Watch, not fixable in theme."})

    # 4 + 5. every URL x every bot
    pages = []
    analyse_bot = a.analyse_as if a.analyse_as in fetch_bots else fetch_bots[0]
    for url in urls:
        row = {"url": url, "status_by_bot": {}, "bytes_by_bot": {}}
        body_for_analysis, theme = None, None
        for token in fetch_bots:
            r = fetch(url, ua=BOTS[token][2])
            time.sleep(a.delay)
            row["status_by_bot"][token] = r["status"] if not r["error"] else r["error"][:60]
            row["bytes_by_bot"][token] = r["bytes"] if r["status"] == 200 else 0
            if token == analyse_bot and r["status"] == 200:
                body_for_analysis, theme = r["body"], served_theme_id(r["headers"])
        statuses = row["status_by_bot"]
        codes = set(statuses.values())
        throttled = [t for t, s in statuses.items() if s == 429]
        other_bad = {t: s for t, s in statuses.items() if s not in (200, 429)}
        if throttled:
            flags.append({"severity": "info", "code": "rate-limited", "page": url,
                          "msg": f"429 after retries for {throttled}: our scan rate tripped Shopify's throttle "
                                 "(not evidence the real crawler is blocked). Re-run slower; never run scans in parallel"})
        if other_bad and len(codes - {429}) == 1:
            code = next(iter(codes - {429}))
            flags.append({"severity": "high", "code": "page-unavailable", "page": url,
                          "msg": f"HTTP {code} for every bot: the page is gone or broken for everyone. If engines "
                                 "send traffic here (check the citation log), add a 301 redirect"})
        elif other_bad:
            for token, s in other_bad.items():
                flags.append({"severity": "critical" if token in CRITICAL_BOTS else "high", "code": "bot-non-200",
                              "page": url, "msg": f"{token} received HTTP {s} while other bots got 200 (bot-specific block)"})
        sizes = [v for v in row["bytes_by_bot"].values() if v]
        if sizes and min(sizes) < 0.5 * max(sizes):
            flags.append({"severity": "high", "code": "bot-content-diff", "page": url,
                          "msg": f"response size varies by bot ({min(sizes)}-{max(sizes)} bytes): possible bot-specific content"})
        row["served_theme_id"] = theme
        if body_for_analysis:
            info, pflags = analyse_page(url, body_for_analysis, truth)
            row.update(info)
            flags += pflags
        pages.append(row)

    themes = {p.get("served_theme_id") for p in pages if p.get("served_theme_id")}
    if len(themes) > 1:
        flags.append({"severity": "info", "code": "mixed-theme-cache", "page": base,
                      "msg": f"pages served by different theme ids {sorted(themes)}: edge cache still holds an old theme"})

    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    seen = set()
    flags = [f for f in flags if not ((f["code"], f["page"], f["msg"]) in seen
                                      or seen.add((f["code"], f["page"], f["msg"])))]
    flags.sort(key=lambda f: (sev_rank.get(f["severity"], 9), f["code"], f["page"]))
    result = {
        "tool": "retro-radius-geo-audit/bot_view.py", "version": "1.0",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base": base, "truth_verified": truth.get("verified"),
        "caveat": "UA-spoof test from a non-bot IP; confirm any block in Bing WT / GSC crawl stats before acting.",
        "bots_fetched": fetch_bots, "analysed_as": analyse_bot,
        "robots": robots, "llms_txt": llms, "http_layer": http_layer, "pages": pages,
        "flag_counts": {s: sum(1 for f in flags if f["severity"] == s) for s in sev_rank},
        "flags": flags,
    }
    s = dump(result, a.out)
    if not a.out:
        print(s)
    else:
        fc = result["flag_counts"]
        print(f"bot_view: {len(pages)} pages x {len(fetch_bots)} bots -> {a.out}")
        print("flags: " + ", ".join(f"{k} {v}" for k, v in fc.items() if v))
        for f in flags:
            if f["severity"] in ("critical", "high"):
                print(f"  [{f['severity']}] {f['code']}: {f['msg']}  ({f['page']})")


if __name__ == "__main__":
    main()
