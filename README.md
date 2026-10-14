# Top AEO-GEO

**A read-only GEO/AEO audit skill for Claude Code, built for a Shopify DTC store (Retro Radius, retroradius.com).** It checks what AI answer engines (ChatGPT, Perplexity, Claude, Copilot, Google AI Overviews) actually receive from the site, whether each page is written to be cited, and whether the facts machines read are true.

> Vietnamese summary: Skill audit GEO/AEO chỉ-đọc cho Claude Code. Nó kiểm tra 4 điều: bot AI thực sự nhận được gì từ website, từng trang có được viết để AI trích dẫn hay không, dữ liệu máy đọc (schema) có đúng sự thật không, và thương hiệu có được web nhận diện không. Kết quả lưu thành scorecard hàng tháng có so sánh với lần quét trước.

The skill folder is `retro-radius-geo-audit/` (the skill id stays the same so existing routines and indexes keep working). Source of truth: `Pinterest Channel/.claude/skills/retro-radius-geo-audit/` in the Retro Radius project. This repo is the packaged copy (see **Sync**).

## Why it exists
It started as an analysis of [zubair-trabzada/geo-seo-claude](https://github.com/zubair-trabzada/geo-seo-claude) (MIT). That repo is a generic agency audit kit. We kept its one real strength, repeatable deterministic diagnostics, and rebuilt it around first-party rules instead of generic folklore:

| | geo-seo-claude | Top AEO-GEO |
|---|---|---|
| Crawler check | parses robots.txt | robots.txt **plus** a real HTTP request as each of 10 AI bots (CDN/WAF blocks never show up in robots.txt) |
| Markdown-for-agents check | trusts the `Content-Type` header | verifies the **body**. Shopify serves HTML labelled `text/markdown`, which the header-only check scores as a false PASS |
| Passage scoring | generic "134-167 words" heuristic | the store's own standard (first sentence = the answer, 40-80-word passage) plus **ship-blocking gates**: false delivery-speed claims, health claims, forbidden brand vocabulary, words that get products blocked in Google Shopping |
| Schema | templates that hard-code 3-7-day shipping | checks the live schema **against the published shipping policy** (catches promises that are faster than reality) |
| Entity | pushes Wikipedia/Wikidata creation | measures what a small brand controls: `sameAs`, consistent bios, independent mentions; never fabricates notability |
| Scoring | one blended 0-100 score with self-declared arbitrary weights | separate sub-scores with no fake composite, reported next to ground truth (AI-referred sessions) and diffed month to month |
| Dependencies | bs4, requests, Playwright, installers that rewrite `~/.claude` | **Python stdlib only**, nothing to install |

## What's inside
```
retro-radius-geo-audit/
  SKILL.md                         instructions Claude follows (modes, rails, routing of findings)
  scripts/bot_view.py              what each AI bot receives: per-bot HTTP, robots, Content-Signal,
                                   llms.txt, Link/UCP, Markdown negotiation, raw-HTML schema vs truth
  scripts/passage_lint.py          deterministic citability lint for a URL or a draft (.html/.md)
  scripts/scorecard.py             dated scorecard + delta vs the previous scan
  scripts/run_scan.py              the monthly full-site scan as 3 sequential phases (botview / lint / scorecard)
  scripts/rrgeo_common.py          stdlib fetch + tiny DOM + JSON-LD helpers
  references/truth-gate.json       the facts machine-readable surfaces must match (shipping, markets, wordlists)
  references/crawler-matrix-2026.md AI bot table + stance + agent-readiness checks
  references/entity-template.json  entity-footprint worksheet
  references/geo-seo-claude-comparison.md  full analysis: what was imported, what was rejected, why
```

## Install
1. Copy `retro-radius-geo-audit/` into your project's `.claude/skills/`.
2. Ask Claude Code for a "GEO audit" or "lint this draft for AEO", or run the scripts directly with Python 3.10+:
```bash
python -I retro-radius-geo-audit/scripts/bot_view.py --urls https://example.com/ https://example.com/products/x --out bot_view.json
python -I retro-radius-geo-audit/scripts/passage_lint.py https://example.com/blogs/news/post --target "the shopper question verbatim"
python -I retro-radius-geo-audit/scripts/scorecard.py --scan-dir scans/2026-10-14
```

## Using it for another store
Edit `references/truth-gate.json` with that store's real shipping/processing times, markets and wordlists, and pass `--base https://yourstore.com`. The SKILL.md routing table points at Retro Radius files; rewrite it for your own workflow.

## Safety
Read-only by design. The scripts only GET public pages, and the skill never writes to the store, the theme or robots.txt. User agents are spoofed from your own IP, so confirm any apparent bot block in Bing Webmaster Tools or Search Console before acting.

## Sync
From the Retro Radius project root (PowerShell):
```powershell
robocopy ".claude\skills\retro-radius-geo-audit" "D:\Pinterest\Top-AEO-GEO\retro-radius-geo-audit" /MIR /XD __pycache__
```

## Changelog
- v1.2 (2026-10-14): `run_scan.py` pipeline for scheduled monthly scans; context-aware vocabulary rule (a brand's style-taxonomy noun is not flagged in category copy).
- v1.1 (2026-10-14): first full-site audit (302 pages, 58 URLs x 10 bots). Fixes found by running it: 429/503 backoff + retries; non-200s split into rate-limited / page-unavailable / bot-specific; Common Questions read from the theme's `<h3>` markup; short PDP answers no longer filtered out of scoring; one penalty per distinct issue in the truth score; forbidden vocabulary downgraded to REVIEW (context decides).
- v1.0 (2026-10-14): first release.
