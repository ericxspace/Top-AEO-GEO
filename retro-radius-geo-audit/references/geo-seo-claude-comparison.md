# geo-seo-claude vs the Retro Radius GEO/AEO stack (analysis, 2026-10-14)

**Repo:** https://github.com/zubair-trabzada/geo-seo-claude (MIT; HEAD `989cae0`, cloned read-only, nothing installed). It is an agency audit kit: one `/geo` orchestrator, 15 sub-skills, 5 parallel subagents, 5 Python scripts (bs4/requests/Playwright), JSON-LD templates, a CRM (prospects, proposals, monthly client reports, PDF export, white-label).

**RR stack it was compared with:** `retro-radius-aeo` (collection answer-shaping + monthly citation check + prompt bank, `18-aeo-geo/`), `seo-geo` (generic GEO reference), `llms-txt-checker`, `retro-radius-organic-search-ops` (Google/Bing ops), the SEO/AEO/GEO Writing Playbook, the PDP spec v2.0, the Truth Gate, and the July audits in `14-agentic-storefront/`.

## Verdict
RR is ahead on everything that decides whether an engine actually cites or sends traffic: a real prompt bank, measured citations, PostHog ground truth on AI-referred sessions (internal numbers live in 18-aeo-geo/citation-check-log.md), a Truth Gate, a claim wall, first-party learnings. The repo has none of that. It only scores the site against generic rubrics.

The repo is ahead on **repeatable, deterministic site diagnostics**. RR did those checks by hand once (2026-07-10, 2026-07-30) and never again. That is the gap this skill fills.

## Imported (adapted)
| Repo component | What RR takes | How it was changed for RR |
|---|---|---|
| `scripts/citability_scorer.py` (passage scoring) | a deterministic per-section lint | Re-based on RR's own standard: 40-80-word answer passage (playbook s2.6, PDP spec s4), first sentence = the answer, no pronoun opener. The repo's 134-167-word "optimum" is reported as info only. Adds the RR gates the repo lacks: Truth Gate speed claims, Google-feed wordlist, forbidden vocabulary, Layer-B health claims, blog prices, tagline placement, and target-phrase placement (H1 + first sentence: the 09-01 and 10-01 learnings). PDP mode reads the exact body from `/products/<handle>.js` and scores each Common Questions answer. |
| `scripts/fetch_page.py` + `geo-crawlers` + `geo-technical` (robots, SSR, headers) | bot-view probe | Also requests each page with every AI bot's user-agent (WAF/CDN blocks show up there, never in robots.txt). No Playwright: Shopify is Liquid-rendered, so raw HTML is what every bot except Gemini sees. Checks that RR's own depth (Common Questions, specs, review JSON-LD, shipping/return schema) is in raw HTML, and checks the schema **against the Truth Gate**. |
| PR drafts: Content-Signal, Markdown negotiation, RFC 8288 Link, Cloudflare-managed robots (merged PR #85) | all four checks | The Markdown check verifies the body, not only the Content-Type. On retroradius.com the repo's version would report a false PASS (HTML served as `text/markdown`). |
| `geo-brand-mentions` + `brand_scanner.py` | an entity-footprint procedure | Wikipedia/Wikidata kept as informational only. RR is not notable enough, and a self-created entry gets deleted and looks like spam. Weight moves to what RR controls: Organization `sameAs`, consistent bios, Reddit (via the existing assist-only routine), independent listings (`14-agentic-storefront/AI_LISTING_PITCH_TARGETS_2026-07-30.md`). |
| `geo-compare` (monthly delta) | a dated scorecard plus a diff against the previous scan | No blended 0-100 composite. The repo admits its weights are "not derived from a controlled study". Sub-scores sit next to ground truth (AI sessions). |
| `geo-crawlers` tiered bot list | the bot table | Extended with the 2025-26 search and user bots the repo lacks (Claude-SearchBot, Claude-User, Perplexity-User, meta-externalagent, DuckAssistBot, MistralAI-User). |

## Rejected, and why
| Repo element | Why not |
|---|---|
| CRM, proposals, PDF report, prospect pipeline, white-label, `/geo update`, curl-pipe-bash installers | agency tooling. RR is one brand, and the installers rewrite `~/.claude`. |
| Market statistics block ("4.4x conversion", "+527%", "Wikipedia 47.9% of ChatGPT citations", "brand mentions 3x backlinks") | vendor/editorial numbers with no primary source. RR's prime rule is that first-party data beats generic best practice. |
| `schema/product-ecommerce.json` | **would break the Truth Gate**: hard-codes transit 3-7 days, handling 0-1 day, 30-day free returns. RR already ships `snippets/rr-ai-schema.liquid` with the true 2-4 + 15-18 values. |
| "2000+ words for ChatGPT", "FAQ section with 5-10 Qs on every page" | conflicts with the binding lean-PDP rule (body <=120 words) and with RR's own measured result (09-01: broad-collection FAQ copy earned zero unbranded citations). |
| llms.txt generator and 10% weight | Shopify now generates `/llms.txt` itself (agent-commerce instructions); Google states it does not use llms.txt. |
| Security-header deductions (CSP, HSTS, X-Frame...) in a GEO score | not a citation factor, and not controllable on Shopify. |
| `speakable`, Wikipedia-creation advice, 50-page crawl | low or no value for a few-hundred-URL store; a Wikipedia article is not attainable. |
| E-E-A-T 0-100 LLM-judged score | unreproducible run to run. RR already enforces authorship, dates and sources in routine 02. |

## Live findings from the first run (2026-10-14), recorded so the next scan can diff them
Full scan: `18-aeo-geo/geo-scans/2026-10-14/` (scorecard: access 100 · machine truth 70 · passage citability 61.5 · entity 16; ground truth = AI-referred sessions in the citation-check log).
1. All 10 tier-1 bots get HTTP 200 on 11 sample URLs: home, 3 top AI-landing PDPs, 2 collections, 3 blog posts, About and the shipping policy. robots.txt blocks none of them. Served theme 167037665340.
2. **Sitewide delivery estimate without a duration.** The cart drawer renders "Arrives Nov 5 – 12" on every page. The homepage, collections and blog posts carry no "15-18 business days" or "3-4 weeks" sentence anywhere in the raw HTML; PDPs ("Ships in 2–4 business days… about 3–4 weeks"), About and the shipping policy do. This is the pattern an engine turned into "RR has a slight advantage for fast shipping" on 2026-10-01.
3. **Shipping schema is ambiguous on calendar vs business days.** `OfferShippingDetails` says handling 2-4 DAY and transit 15-18 DAY with no `businessDays`, while the policy says business days (≈3-4 weeks). Google's merchant-listing docs (checked 2026-10-14) do not define the default, so engines may read about one week faster than the truth. Candidate fix: add `businessDays` Mon-Fri to `deliveryTime` in `rr-ai-schema.liquid` (theme change → stage, Eric publishes).
4. Organization `sameAs` has 3 profiles (Pinterest, Instagram, Facebook). TikTok (`@retroradiushome`) and YouTube (`UCHqeii4Ce2xmi8UzXkq_bsg`) are connected in Metricool and routine 05 posts to them, but both are missing from `sameAs`.
5. PDP Common Questions answers on the top AI-landing lamp run 18-25 words. PDP spec s4 / playbook s6 set 40-80 as the citation unit. The 3 sampled PDPs lint at 51-67.
6. Lighting collection: the H1 is still "Lighting". The target phrase sits in the SEO title, meta and intro, which confirms rework row L5.
7. The oldest blog post `dopamine-decor-trend-2026` gets ChatGPT landings and lints at 45: 0 blocks with a number plus a source, and few question H2s. It is the strongest refresh candidate. `gen-z-living-room` sits at 72.5 with 1 cited stat.
8. Entity: no independent web mentions, no Reddit threads and no third-party YouTube were found (WebSearch; Reddit JSON returned 403). No Wikidata item, which is expected. Branded prompts 2/5 as of 10-01. The off-site footprint, not on-site copy, is the weakest sub-score.
9. `mushroom-table-lamp-metal-cordless` body is 168 words, over the 120 cap. This comes from the 2026-09-23 approved answer-first retrofit (11 top sellers at 147-169 words), so it is a standards conflict for Eric, not a regression.
