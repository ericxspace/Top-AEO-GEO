---
name: retro-radius-geo-audit
description: Repeatable, read-only GEO diagnostics for retroradius.com covering what AI crawlers actually receive (per-bot HTTP access, robots/Content-Signal/Markdown/Link/llms.txt, raw-HTML schema checked against the Truth Gate), a deterministic passage-citability lint for any blog post, collection, PDP or draft, an entity-footprint check, and a dated monthly scorecard with deltas. Use for "GEO audit", "AI crawler check", "can ChatGPT/Perplexity see our pages", "is this post citable", "lint this draft for AEO", "entity / brand mentions", "geo scan", "monthly GEO scorecard", or before/after a theme or schema change. Not for writing copy (retroradius-blog / retro-radius-aeo) or for measuring citations (retro-radius-aeo section C).
---

# Retro Radius GEO audit: bot view, passage lint, entity, scorecard

**v1.0 (2026-10-14).** Built from an analysis of github.com/zubair-trabzada/geo-seo-claude, keeping only what RR lacked: deterministic, repeatable site diagnostics. The comparison (what was imported, what was rejected, first-run findings) is in `references/geo-seo-claude-comparison.md`. Read it before extending this skill.

## Where this sits (do not duplicate)
| Need | Use |
|---|---|
| Write or retrofit collection copy, prompt bank, monthly citation check | `retro-radius-aeo` |
| Write blog posts | `/retroradius-blog` (routine 02) |
| Indexation, sitemaps, GSC/Bing ops | `retro-radius-organic-search-ops` |
| Generic GEO background (platform stats, Google's position) | `seo-geo` (reference only) |
| **Is the site machine-readable and truthful to bots? Is this page citable by RR's standard? Did it get better since last month?** | **this skill** |

Ground truth always beats these diagnostics: AI-referred sessions in PostHog (method in `18-aeo-geo/aeo-learnings.md` 2026-10-01) and the citation log. A scan that "improves" while AI sessions fall means the scan measures the wrong thing. Say so.

## Rails (non-negotiable)
- **Read-only.** The scripts only GET public storefront URLs. Never write to Shopify, the theme, robots.txt or metafields from this skill. Findings become worklist rows, tickets or proposals for Eric (theme changes: stage on a duplicate theme, Eric publishes; batch store edits need Eric's OK).
- **Truth Gate** (`18-aeo-geo/AEO_Visibility_System_2026-08-01.md` §3) and `references/truth-gate.json`: re-verify that file against live policies when `verified` is more than 30 days old, and update it in the same session.
- Never create Wikipedia/Wikidata entries, never post on Reddit (assist-only rule), never buy listings or links.
- Spoofed user-agents are a strong but imperfect proxy. Confirm any bot block in Bing WT / GSC crawl stats before acting on it.
- Run Python with `-I`. Scripts are stdlib-only (Python 3.10+), so no install step is needed.
- **One scan at a time, `--delay` ≥ 0.3.** On 2026-10-14, a bot-view scan and a catalog-wide lint run in parallel drew HTTP 429 from Shopify on 55 bot × URL pairs. `fetch()` now backs off and retries, and a 429 that survives the retries is reported as `rate-limited` (info): it is our own scan rate, never evidence of a bot block. A non-200 on every bot is `page-unavailable` (a dead page). Only a status that differs by bot counts as a bot block.

Paths below are relative to `D:\Pinterest\Pinterest Channel`. `S=.claude/skills/retro-radius-geo-audit/scripts`.

## 1. BOT VIEW: what crawlers receive (`bot_view.py`, ~1 min)
```
python -I "$S/bot_view.py" --urls <home> <top AI-landing PDPs> <2 collections> <1-2 blog posts> <about> <shipping policy> --out <scan-dir>/bot_view.json
```
- Take the PDP sample from the latest `18-aeo-geo/citation-check-log.md` "Top AI landing PDPs" line; those are the pages engines actually send people to. Without `--urls` it samples the sitemap (`--products 3`).
- `--bots tier1` (default, 10 bots) | `all` | a comma list. The bot table and RR's allow-all stance are in `references/crawler-matrix-2026.md`.
- Output: robots verdict per bot, Content-Signal, Cloudflare-managed block, llms.txt kind, Link rels, Markdown negotiation (strict vs fallback, body-verified), status/bytes per URL × bot, served theme id, and per page the JSON-LD types, `sameAs`, aggregateRating, shipping/return schema vs truth, Common Questions/specs presence, speed claims, Google-feed wordlist hits in synced fields.
- Severity guide. **critical**: a search bot blocked, noindex, or schema promising faster delivery than policy. **high**: a speed claim in text, feed-wordlist hit, null rating, no Product schema. **medium**: missing shipping/return schema, a date estimate with no duration, calendar/business-day ambiguity. **info**: watch items.

## 2. PASSAGE LINT: is this page citable by OUR standard? (`passage_lint.py`, seconds)
```
python -I "$S/passage_lint.py" <url | draft.html | draft.md> [--type article|collection|product] [--target "<prompt-bank prompt verbatim>"] [--out <scan-dir>/passages/<handle>.json]
```
- Per section: answer-first (30), answer length 40-80 (20), self-contained (15), evidence (20: numbers with units, plus named or linked sources on blog posts), structure (15). Page score = mean over question sections.
- Page checks: target phrase in H1 / first sentence / SEO title / meta (verbatim or all-terms); blog posts get ≥3 question H2s, a FAQ, ≥5 cited stats, the answer in the first 30%, and an Updated label once the post is more than 180 days old; collections get intro ≤100 and total 250-400 words; PDPs get body ≤120 and ≥3 Common Questions.
- **Gates (FAIL = do not ship):** Truth-Gate speed claims; Layer-B health claims on PDP/collection copy (REVIEW on blog: must be hedged and Science-Bank-sourced); PDP forbidden vocabulary; Google-feed wordlist in the PDP body. REVIEW: we/our/us in PDP copy, $ prices in blog posts, the tagline in collections.
- Use it **before publishing** (paste the draft HTML/MD into a scratch file) and **after**, on the live URL. Routine 02 and the PDP work can call it as a lint step; wiring it into a routine is Eric's call (see §5).

## 3. ENTITY: does the web know who Retro Radius is? (manual procedure, ~15 min)
Copy `references/entity-template.json` to `<scan-dir>/entity.json` and fill it from checks run **this session**:
1. `organization_sameAs`: from `bot_view.json`. Compare it with the accounts that actually exist (Metricool `getBrandSettings` lists the connected networks). A missing live profile is a quick win for the theme snippet `rr-ai-schema.liquid`.
2. `profiles[]`: for each profile, does the bio define RR the same way as the homepage meta description? Engines quote that definition (09-01 learning).
3. `independent_mentions`: WebSearch `"Retro Radius" decor -site:retroradius.com` plus `"retroradius.com"`. Count only independent pages (not our own socials or marketplaces we list on).
4. `reddit_threads_mentioning`: try `https://www.reddit.com/search.json?q=%22retro%20radius%22&limit=50` (read-only public JSON). It returned **HTTP 403 from Eric's machine on 2026-10-14**; if it does again, fall back to WebSearch `site:reddit.com "retro radius"` and say which method you used. Count threads that are about the store.
5. `youtube_third_party`: WebSearch `site:youtube.com "Retro Radius"`.
6. `wikidata`: `https://www.wikidata.org/w/api.php?action=wbsearchentities&search=Retro%20Radius&language=en&format=json`. Informational only.
7. `branded_prompts` and `ground_truth`: copy from the latest citation-check-log entry and PostHog. Never estimate.
Actions route to `14-agentic-storefront/AI_LISTING_PITCH_TARGETS_2026-07-30.md` (listings), the Reddit routine (owner-honest threads, Eric posts), and the theme snippet (sameAs).

## 4. SCORECARD: monthly, dated, diffed (`scorecard.py`)
```
python -I "$S/scorecard.py" --scan-dir "18-aeo-geo/geo-scans/<YYYY-MM-DD>"
```
The scan folder holds `bot_view.json`, `passages/*.json` and `entity.json`. The script writes `scorecard.json` + `scorecard.md` and diffs them against the latest older scan. Four sub-scores (access, machine truth & parity, passage citability, entity footprint) sit next to ground truth. There is **no blended composite** on purpose. Report deltas and resolved/new flags, then route each open item:

| Finding | Route |
|---|---|
| Bot blocked / non-200 | confirm in Bing WT + GSC → `retro-radius-organic-search-ops`; Eric if robots.txt.liquid is needed |
| Schema vs Truth Gate, sameAs, businessDays | theme snippet `rr-ai-schema.liquid`: stage on a duplicate theme → Eric publishes |
| Delivery estimate without duration | theme (cart drawer / announcement) proposal → Eric |
| Collection target/H1 misses | `18-aeo-geo/collection-retrofit-worklist.md` row → `retro-radius-aeo` |
| Blog lint misses | `06-operations/blog-routine/blog-learnings.md` or a refresh row for routine 02 |
| PDP Common Questions too short | PDP AEO list (`18-aeo-geo/PDP_AEO_Audit_*.md`); batch metafield edits need Eric's OK |
| Entity gaps | AI listing targets doc / Reddit routine / Eric for profile bios |

## Known exceptions (do not "fix" without Eric)
- **PDP body >120 words on 11 top sellers.** The PDP AEO retrofit of 2026-09-23 (Hermes, Eric-approved) deliberately rewrote 11 top-seller bodies answer-first at 147-169 words (memory `pdp-aeo-retrofit-2026-09-23`). The playbook's binding mobile rule says a hard cap of 120. `passage_lint` reports `pdp-body-cap` MISS on them. Report it as a **standards conflict for Eric to rule on**, not as a defect.
- **Strict `Accept: text/markdown` → 404** on PDPs/collections. This is Shopify platform behaviour; nothing in the theme can change it.
- **`/llms.txt` is Shopify's agent-commerce file.** Never replace it with a content map.

## 5. Cadence (proposed, not wired)
Run §1-§4 once a month, the day before `aeo-citation-check` (1st, 10:00), so the check reads a fresh scorecard. Also run §1 after every theme publish, after waiting out the edge cache: compare `served_theme_id` with the MAIN theme first. Adding this to a scheduled routine changes the routine system, so it needs Eric's approval and the standing-rule protocol (CLAUDE.md + routine prompt + `FLEET_CHARTER.md`).

## Changelog
- **v1.1, 2026-10-14:** first full-site audit (`18-aeo-geo/GEO_Audit_2026-10-14.md`). Added 429/503 backoff and retries, and split non-200 results into rate-limited / page-unavailable / bot-specific. Articles are now sampled from `sitemap_articles_*`. Published as the GitHub repo **Top AEO-GEO**.
- **v1.0, 2026-10-14:** created from the geo-seo-claude analysis. First scan: `18-aeo-geo/geo-scans/2026-10-14/`.
