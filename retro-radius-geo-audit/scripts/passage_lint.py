#!/usr/bin/env python3
"""passage_lint.py: deterministic AI-citability lint for ONE Retro Radius page or draft.

Scores every heading-bounded section against the RR writing standard
(11-skills-research/SEO_AEO_GEO_Writing_Playbook_2026-07-10.md + 18-aeo-geo/aeo-learnings.md),
not against generic GEO folklore:
  - the first sentence under a heading IS the answer (no pronoun/filler opener, <=35 words, concrete)
  - the answer passage is 40-80 words and self-contained
  - evidence: numbers with units / named, linked sources
  - short paragraphs, lists where they help
and runs the hard gates that block shipping: Truth Gate speed claims, Google-feed wordlist (PDP body),
PDP forbidden vocabulary, Layer-B health claims, hardcoded blog prices, tagline in collections.

Input: a live URL (blog article, collection, PDP) or a local draft (.html / .md / .txt).
  python passage_lint.py <url|file> [--type auto|article|collection|product]
                         [--target "shopper prompt verbatim"] [--json] [--out file.json]
For a PDP URL the lean body comes from the public /products/<handle>.js endpoint (exact
descriptionHtml) and the Common Questions accordion is scored answer by answer.

Score = mean of question-section scores (all sections if none are questions). It is a lint, not a
prediction: ground truth stays the monthly citation check + AI-referred sessions in PostHog.
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timezone  # noqa: E402

from rrgeo_common import (BROWSER_UA, Node, contains_phrase, dump, fetch, find_all, first,  # noqa: E402
                          iter_nodes, iter_typed, jsonld_blocks, load_json, meta_content, norm_phrase,
                          parse_html, sentences, text_of, types_of, words)

HERE = os.path.dirname(os.path.abspath(__file__))
TRUTH = load_json(os.path.normpath(os.path.join(HERE, "..", "references", "truth-gate.json")))

PRONOUN_START = re.compile(r"^(it|its|it's|this|that|these|those|they|them|their|he|she|so|and|but|also|"
                           r"however|well|great question|here's the thing|as mentioned)\b", re.I)
PRONOUNS = re.compile(r"\b(it|they|them|their|this|that|these|those|he|she|his|her)\b", re.I)
QUESTION_WORDS = re.compile(r"^(how|what|why|which|can|do|does|is|are|should|where|when|will|who|"
                            r"could|would|did|has|have)\b", re.I)
UNIT_NUM = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:%|cm|mm|m\b|in\b|inch(?:es)?|ft|feet|lbs?|kg|g\b|oz|w\b|watts?|"
                      r"lumens?|lm\b|k\b|hours?|hrs?|mins?|minutes|days?|weeks?|months?|years?|"
                      r"x\b|times|people|percent|respondents|participants)", re.I)
ATTRIB = re.compile(r"\b(according to|study|studies|research|researchers|survey|report(?:ed)?|"
                    r"published|journal|university|found that|data from|meta-analysis|trial)\b|\(\s?(?:19|20)\d{2}\s?\)", re.I)
STOP = set("the a an of to for in on and or with your you my is are do does can how what why which "
           "should i it be at by from this that".split())
PRICE = re.compile(r"\$\s?\d")
TAGLINE = re.compile(r"decorate your mood", re.I)
# "vibe(s)" naming RR's style taxonomy: "shop by vibe", "across our Dopamine, Memphis and Eclectic vibes"
TAXONOMY_VIBE = re.compile(r"(\b(by|between|across|explore the|find your|whole|every|our)\b[^.]{0,6}\bvibes?\b"
                           r"|\b(dopamine|memphis|mid-century|eclectic)\b[^.]{0,70}\bvibes?\b)", re.I)


# ---------------------------------------------------------------- content extraction

def blocks(node):
    """Flatten a content node into ordered (kind, text, external_links) blocks."""
    for c in node.children:
        if isinstance(c, str):
            if c.strip() and len(c.split()) > 2:
                yield ("p", re.sub(r"\s+", " ", c).strip(), 0)
            continue
        if c.tag in ("script", "style", "noscript", "svg", "template", "iframe", "nav", "aside", "form",
                     "footer", "header", "button", "select"):
            continue
        if re.fullmatch(r"h[1-6]", c.tag):
            yield (c.tag, text_of(c), 0)
            continue
        if c.tag in ("p", "li", "blockquote", "figcaption", "td", "th", "dt", "dd", "summary"):
            t = text_of(c)
            if t:
                ext = sum(1 for a in find_all(c, "a")
                          if a.get("href").startswith("http") and "retroradius.com" not in a.get("href"))
                yield ("li" if c.tag in ("li", "dd", "td") else "p", t, ext)
            continue
        yield from blocks(c)


def pick_container(root, ptype):
    if ptype == "article":
        arts = sorted(find_all(root, "article"), key=lambda n: len(words(text_of(n))), reverse=True)
        if arts:
            rtes = [n for n in iter_nodes(arts[0]) if "rte" in n.get("class").split()]
            return max(rtes, key=lambda n: len(words(text_of(n)))) if rtes else arts[0]
    if ptype == "collection":
        for n in iter_nodes(root):
            if "collection__description" in n.get("class").split():
                return n
    return first(root, "main") or first(root, "body") or root


def md_blocks(text):
    out, para = [], []

    def flush():
        if para:
            out.append(("p", " ".join(para).strip(), len(re.findall(r"\]\(https?://(?!retroradius)", " ".join(para)))))
            para.clear()
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            flush()
            out.append((f"h{len(m.group(1))}", m.group(2).strip(), 0))
        elif re.match(r"^([-*+]|\d+[.)])\s+", s):
            flush()
            item = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
            out.append(("li", item, len(re.findall(r"\]\(https?://(?!retroradius)", item))))
        elif not s:
            flush()
        else:
            para.append(s)
    flush()
    return [(k, re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t).replace("**", "").replace("*", ""), e)
            for k, t, e in out]


def sectionize(blks, h1_fallback=""):
    secs, cur = [], {"heading": h1_fallback or "(intro)", "level": 1, "blocks": []}
    h1 = h1_fallback
    for kind, text, ext in blks:
        if kind == "h1":
            h1 = h1 or text
            cur["heading"] = text
            continue
        if kind in ("h2", "h3", "h4"):
            secs.append(cur)
            cur = {"heading": text, "level": int(kind[1]), "blocks": []}
            continue
        if kind in ("h5", "h6"):
            continue
        cur["blocks"].append((kind, text, ext))
    secs.append(cur)
    return [s for s in secs if s["blocks"]], h1


def faq_sections_from_details(d):
    """Theme 1.0.32+ renders one <h3> per Common Question (snippets/rr-aeo-block.liquid): read it
    structurally; fall back to splitting 'Question? Answer.' text for older markup."""
    h3s = [h for h in find_all(d, "h3") if text_of(h).rstrip().endswith("?")]
    if not h3s:
        content = [c for c in d.children if isinstance(c, Node) and c.tag != "summary"]
        return faq_sections_from_text(" ".join(text_of(c) for c in content))
    out = []
    for h in h3s:
        sib = [c for c in h.parent.children if isinstance(c, Node) or (isinstance(c, str) and c.strip())]
        ans, started = [], False
        for c in sib:
            if c is h:
                started = True
                continue
            if not started:
                continue
            if isinstance(c, Node) and (c.tag == "h3" or find_all(c, "h3")):
                break
            ans.append(c.strip() if isinstance(c, str) else text_of(c))
        answer = " ".join(a for a in ans if a)
        if answer:
            out.append({"heading": text_of(h), "level": 3, "blocks": [("p", answer, 0)]})
    return out


def faq_sections_from_text(text):
    """Split 'Question? Answer. Question? Answer.' accordion text into sections."""
    out = []
    for m in re.finditer(r"([A-Z][^?]{8,220}\?)\s+(.+?)(?=\s+[A-Z][^?.!]{8,220}\?\s|$)", text):
        out.append({"heading": m.group(1).strip(), "level": 3, "blocks": [("p", m.group(2).strip(), 0)]})
    return out


# ---------------------------------------------------------------- scoring

def is_question(h):
    h = h.strip()
    return h.endswith("?") or bool(QUESTION_WORDS.match(h))


def score_section(sec, ptype):
    heading = sec["heading"]
    paras = [t for k, t, _ in sec["blocks"]]
    answer = paras[0]
    i = 1
    while len(words(answer)) < 20 and i < len(paras):
        answer = answer + " " + paras[i]
        i += 1
    sents = sentences(answer)
    first_s = sents[0] if sents else answer
    fw = len(words(first_s))
    aw = len(words(answer))
    q = is_question(heading)
    head_terms = {w for w in norm_phrase(heading) if w not in STOP and len(w) > 2}
    concrete = (bool(re.search(r"\d", first_s)) or bool(re.match(r"^(yes|no)\b", first_s, re.I))
                or bool(head_terms & set(norm_phrase(first_s))))
    notes = []

    s_first = 0
    if not PRONOUN_START.match(first_s) and fw <= 35:
        s_first = 30 if (concrete or not q) else 15
    if PRONOUN_START.match(first_s):
        notes.append(f"opens with '{first_s.split()[0]}': first sentence must stand alone")
    if fw > 35:
        notes.append(f"first sentence {fw} words (>35)")
    if q and not concrete:
        notes.append("first sentence does not answer with a number, yes/no or the heading's own terms")

    s_len = 20 if 40 <= aw <= 80 else 10 if (30 <= aw < 40 or 80 < aw <= 110) else 0
    if s_len < 20:
        notes.append(f"answer passage {aw} words (target 40-80)")

    sec_text = " ".join(paras)
    sw = max(len(words(sec_text)), 1)
    s_self = (5 if not PRONOUN_START.match(first_s) else 0)
    s_self += 5 if len(PRONOUNS.findall(sec_text)) / sw < 0.04 else 0
    s_self += 5 if (re.search(r"\d", sec_text) or re.search(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}", sec_text)) else 0

    nums = len(UNIT_NUM.findall(sec_text))
    ext = sum(e for _, _, e in sec["blocks"])
    attributed = bool(ATTRIB.search(sec_text)) or ext > 0
    s_ev = (10 if nums >= 2 else 5 if nums == 1 else 0)
    if ptype == "article":
        s_ev += 10 if attributed else 0
    else:
        s_ev += 10 if nums >= 3 else 5 if nums >= 1 else 0

    lens = [len(words(t)) for t in paras]
    has_list = any(k == "li" for k, _, _ in sec["blocks"])
    s_struct = (10 if (sum(lens) / len(lens)) <= 60 else 5 if (sum(lens) / len(lens)) <= 90 else 0) + (5 if has_list or len(paras) == 1 else 0)
    if sum(lens) / len(lens) > 90:
        notes.append("paragraphs average >90 words")

    total = s_first + s_len + s_self + s_ev + s_struct
    return {"heading": heading[:120], "question": q, "first_sentence_words": fw, "answer_words": aw,
            "section_words": sw, "numbers_with_units": nums, "attributed": attributed,
            "score": total, "breakdown": {"answer_first": s_first, "answer_length": s_len,
                                          "self_contained": s_self, "evidence": s_ev, "structure": s_struct},
            "repo_134_167_window": 134 <= sw <= 167, "notes": notes}


def gates(text, ptype, scope_label):
    out = []

    def g(level, code, msg):
        out.append({"level": level, "code": code, "scope": scope_label, "msg": msg})
    for pat in TRUTH["speed_claim_patterns"]:
        m = re.search(pat, text, re.I)
        if m:
            g("FAIL", "truth-speed-claim", f"'{m.group(0)}' (delivery is {TRUTH['transit_business_days'][0]}-"
              f"{TRUTH['transit_business_days'][1]} business days + processing)")
    for pat in TRUTH["health_claim_patterns"]["patterns"]:
        m = re.search(pat, text, re.I)
        if m:
            g("FAIL" if ptype in ("product", "collection") else "REVIEW", "health-claim",
              f"'{m.group(0)}': Layer B never; Layer A only hedged + Science Bank source")
    for term in TRUTH["forbidden_vocabulary"]["terms"]:
        hits = list(re.finditer(r"\b" + re.escape(term) + r"\b", text, re.I))
        if term == "vibes" and ptype == "collection":
            # Ruling 2026-10-14: in collections "vibe(s)" is fine as the style-taxonomy noun
            hits = [h for h in hits if not TAXONOMY_VIBE.search(text[max(0, h.start() - 80):h.end() + 5])]
        m = hits[0] if hits else None
        if m:
            # REVIEW, not FAIL: context decides ("Premium Silver" is a supplier variant name,
            # "energy-efficient LED" is a spec), and only a human can tell (first audit, 2026-10-14)
            g("REVIEW", "forbidden-vocab", f"'{m.group(0)}' (PDP spec s0.3; check context)")
    if ptype == "product":
        for term in TRUTH["google_feed_wordlist"]["terms"]:
            if re.search(r"\b" + re.escape(term) + r"\b", text, re.I):
                g("FAIL", "feed-wordlist", f"'{term}' in the PDP body = a Google-synced field")
        if re.search(r"\b(we|our|us)\b", text):
            g("REVIEW", "first-person-plural", "'we/our/us' in product copy (spec s0.3)")
    if ptype == "article" and PRICE.search(text):
        g("REVIEW", "hardcoded-price", "a $ amount in a blog post: product cards carry no prices; prices drift")
    if ptype == "collection" and TAGLINE.search(text):
        g("REVIEW", "tagline-in-collection", "tagline belongs on pins / blog CTA / email PS, not collections")
    return out


# ---------------------------------------------------------------- main

def guess_type(src):
    p = urlparse(src).path if src.startswith("http") else ""
    if "/products/" in p:
        return "product"
    if p.startswith("/collections/"):
        return "collection"
    if p.startswith("/blogs/"):
        return "article"
    return "article"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("--type", default="auto", choices=["auto", "article", "collection", "product"])
    ap.add_argument("--target", default="", help="shopper prompt / exact phrase the page must own")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ptype = guess_type(a.src) if a.type == "auto" else a.type
    page = {"src": a.src, "type": ptype, "target": a.target or None}
    meta_title = meta_desc = ""
    full_visible = ""
    extra_secs = []

    if a.src.startswith("http"):
        r = fetch(a.src, ua=BROWSER_UA)
        if r["status"] != 200:
            print(f"fetch failed: HTTP {r['status']} {r['error'] or ''}")
            sys.exit(2)
        root = parse_html(r["body"])
        t = first(root, "title")
        meta_title = text_of(t) if t else ""
        meta_desc = meta_content(root, name="description")
        full_visible = text_of(first(root, "body") or root)
        typed = [d for o in jsonld_blocks(root)[0] for d in iter_typed(o)]
        page["faq_schema_questions"] = sum(len(d.get("mainEntity") or []) for d in typed if "FAQPage" in types_of(d))
        page["date_published"] = next((d.get("datePublished") for d in typed if d.get("datePublished")), None)
        h1n = first(root, "h1")
        h1 = text_of(h1n) if h1n else ""
        if ptype == "product":
            js = fetch(a.src.split("?")[0].rstrip("/") + ".js")
            try:
                desc_html = json.loads(js["body"]).get("description", "")
            except Exception:
                desc_html = None
                page["pdp_body_error"] = f"/products/<handle>.js HTTP {js['status']}: body not measured"
            body_root = parse_html(desc_html or "")
            blks = list(blocks(body_root))
            for d in find_all(root, "details"):
                summ = first(d, "summary")
                if summ and re.search(r"question", text_of(summ), re.I):
                    extra_secs += faq_sections_from_details(d)
        else:
            blks = list(blocks(pick_container(root, ptype)))
    else:
        raw = open(a.src, encoding="utf-8").read()
        h1 = ""
        if a.src.lower().endswith((".md", ".markdown", ".txt")):
            blks = md_blocks(raw)
        else:
            blks = list(blocks(parse_html(raw)))
        full_visible = " ".join(t for _, t, _ in blks)

    secs, h1 = sectionize(blks, h1)
    if ptype == "product":
        body_text = " ".join(t for k, t, _ in blks if k in ("p", "li"))
        page["pdp_body_words"] = None if page.get("pdp_body_error") else len(words(body_text))
        secs = extra_secs  # the lean body is a hook, not an answer passage; score the Q&A
    body_text_all = " ".join(t for k, t, _ in blks if k in ("p", "li"))
    min_words = 3 if ptype == "product" else 15   # short PDP answers are the finding, never filter them out
    scored = [score_section(s, ptype) for s in secs
              if len(words(" ".join(t for _, t, _ in s["blocks"]))) >= min_words and not TAGLINE.search(s["heading"])]
    qs = [s for s in scored if s["question"]]
    basis = qs or scored
    page["score"] = round(sum(s["score"] for s in basis) / len(basis), 1) if basis else None
    page["sections_scored"] = len(scored)
    page["question_sections"] = len(qs)
    page["h1"] = h1

    checks = []

    def chk(ok, code, msg):
        checks.append({"pass": bool(ok), "code": code, "msg": msg})

    intro_first = ""
    if blks:
        firsts = [t for k, t, _ in blks if k == "p"]
        intro_first = sentences(firsts[0])[0] if firsts and sentences(firsts[0]) else ""
    total_w = len(words(body_text_all))
    if a.target:
        def stem(ws):
            return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in ws}
        tterms = stem(w for w in norm_phrase(a.target) if w not in STOP)

        def target_chk(field_text, code, msg):
            if contains_phrase(field_text, a.target):
                chk(True, code, msg + " [verbatim]")
            elif tterms and tterms <= stem(norm_phrase(field_text)):
                chk(True, code, msg + " [all terms, not verbatim: fine for SEO, BOFU titles should be the prompt verbatim]")
            else:
                missing = sorted(tterms - stem(norm_phrase(field_text)))
                chk(False, code, msg + f" [missing: {', '.join(missing)}]")
        target_chk(h1, "target-in-h1", f"H1 carries the target (H1 = '{h1[:90]}')")
        target_chk(intro_first, "target-in-first-sentence",
                   "target in the intro's first sentence (09-01 learning: meta-only phrasing does not win)")
        if meta_title or meta_desc:
            target_chk(meta_title, "target-in-seo-title", f"SEO title = '{meta_title[:90]}'")
            target_chk(meta_desc, "target-in-meta-desc", "meta description (Bing literal-phrase rule)")
    if ptype == "article":
        h2q = sum(1 for s in secs if s["level"] == 2 and is_question(s["heading"]))
        chk(h2q >= 3, "question-h2s", f"{h2q} question-form H2s (aim >=3, one per fan-out sub-query)")
        q_h3 = sum(1 for s in secs if s["level"] == 3 and is_question(s["heading"]))
        faq = (any(re.search(r"\bFAQ|frequently asked|questions\b", s["heading"], re.I) for s in secs)
               or q_h3 >= 3 or page.get("faq_schema_questions", 0) >= 3)
        chk(faq, "faq-block", f"FAQ block present (question H3s {q_h3}, FAQPage Qs {page.get('faq_schema_questions', 'n/a')})")
        stats = sum(1 for _, t, e in blks if re.search(r"\d", t) and (e > 0 or ATTRIB.search(t)))
        chk(stats >= 5, "cited-stats", f"{stats} blocks with a number + source/link (blog floor >=5)")
        if full_visible and a.src.startswith("http"):  # drafts have no publish date yet
            age_days = None
            try:
                pub = datetime.fromisoformat(str(page.get("date_published")).replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - pub).days
            except (TypeError, ValueError):
                pass
            labelled = bool(re.search(r"\bUpdated\s+[A-Z][a-z]+\s+\d{4}", full_visible))
            if labelled or (age_days is not None and age_days < 180):
                chk(True, "updated-label", "fresh: " + ("'Updated <Month Year>' visible" if labelled
                                                        else f"published {age_days} days ago, no refresh due yet"))
            else:
                chk(False, "updated-label", f"published {age_days if age_days is not None else '?'} days ago and no "
                    "'Updated <Month Year>': refresh it (commercial citations skew to pages updated <=12 months)")
        if qs:
            acc, first_q_offset = 0, None
            for s in secs:
                if is_question(s["heading"]) and first_q_offset is None:
                    first_q_offset = acc
                acc += len(words(" ".join(t for _, t, _ in s["blocks"])))
            frac = (first_q_offset or 0) / max(total_w, 1)
            chk(frac <= 0.30, "answer-in-first-30pct", f"first question answered at {frac:.0%} of the page (~55% of AIO citations come from the first 30%)")
    if ptype == "collection":
        intro_w = len(words(" ".join(t for _, t, _ in secs[0]["blocks"]))) if secs and secs[0]["level"] == 1 else 0
        chk(intro_w <= 100, "collection-intro", f"intro above the grid {intro_w} words (<=100)")
        chk(250 <= total_w <= 400, "collection-length", f"description {total_w} words (250-400)")
    if ptype == "product":
        bw = page.get("pdp_body_words")
        if bw is None:
            chk(False, "pdp-body-unmeasured", page.get("pdp_body_error", "body not measured"))
        else:
            chk(bw <= 120, "pdp-body-cap", f"PDP body {bw} words (hard cap 120; aim 60-100)")
        chk(len(extra_secs) >= 3, "pdp-common-questions", f"{len(extra_secs)} Common Questions answers found in raw HTML")

    gate_text = body_text_all if ptype != "product" else " ".join(t for k, t, _ in blks)
    gl = gates(gate_text, ptype, "body")
    if ptype == "product" and extra_secs:
        gl += [x for x in gates(" ".join(t for s in extra_secs for _, t, _ in s["blocks"]), "collection", "common_questions")
               if x["code"] in ("truth-speed-claim", "health-claim")]
    page["checks"] = checks
    page["gates"] = gl
    page["ship_blocked"] = any(x["level"] == "FAIL" for x in gl)
    page["sections"] = scored

    if a.out:
        dump(page, a.out)
    if a.json:
        print(dump(page))
        return
    print(f"passage_lint [{ptype}] {a.src}")
    print(f"  score {page['score']} over {len(basis)} {'question ' if qs else ''}sections"
          f"{'  |  SHIP BLOCKED' if page['ship_blocked'] else ''}")
    for c in checks:
        print(f"  {'PASS' if c['pass'] else 'MISS'}  {c['code']}: {c['msg']}")
    for x in gl:
        print(f"  {x['level']:6} {x['code']} [{x['scope']}]: {x['msg']}")
    for s in sorted(scored, key=lambda s: s["score"])[:8]:
        print(f"  {s['score']:3}  {s['heading'][:70]}  -> {'; '.join(s['notes']) or 'ok'}")


if __name__ == "__main__":
    main()
