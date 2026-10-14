# AI crawler matrix: Retro Radius stance (2026-10-14)

Source of the bot list: geo-seo-claude `skills/geo-crawlers` (14 bots, early 2026), extended with the 2025-26 user-fetch and search bots it lacks (Claude-SearchBot, Claude-User, Perplexity-User, meta-externalagent, DuckAssistBot, MistralAI-User). `scripts/bot_view.py` carries the same table in `BOTS`; edit both together.

**RR stance: allow everything. Change nothing without Eric.** Retro Radius wants to be found by every answer engine, and Shopify's default `robots.txt` already allows all of these bots (verified 2026-10-14: no AI-specific groups, `User-agent: *` allows products/collections/blogs/pages). The store has no custom `robots.txt.liquid`. Adding one is a theme change: stage it on a duplicate theme and let Eric publish.

| Tier | Token | What it feeds | Fetch UA? | RR stance |
|---|---|---|---|---|
| 1 | OAI-SearchBot | ChatGPT search index | yes | allow (critical) |
| 1 | ChatGPT-User | ChatGPT live fetch for a user | yes | allow (critical) |
| 1 | GPTBot | OpenAI crawl (training + corpus) | yes | allow |
| 1 | bingbot | Bing index = ChatGPT/Copilot grounding | yes | allow (critical) |
| 1 | Googlebot | Google index = AI Overviews / AI Mode | yes | allow (critical) |
| 1 | PerplexityBot | Perplexity index | yes | allow (critical) |
| 1 | Perplexity-User | Perplexity live fetch | yes | allow |
| 1 | ClaudeBot | Anthropic crawl | yes | allow |
| 1 | Claude-SearchBot | Claude search index | yes | allow (critical) |
| 1 | Claude-User | Claude live fetch | yes | allow |
| 2 | Google-Extended | robots token only: Gemini use. Blocking it does NOT remove pages from AI Overviews | no | allow |
| 2 | Applebot / Applebot-Extended | Siri/Spotlight; -Extended = Apple training token | yes / no | allow |
| 2 | meta-externalagent | Meta AI | yes | allow |
| 2 | Amazonbot | Alexa / Rufus | yes | allow |
| 2 | DuckAssistBot | DuckDuckGo AI answers | yes | allow |
| 2 | MistralAI-User | Le Chat live fetch | yes | allow |
| 3 | CCBot | Common Crawl (training only) | yes | allow (no reason to block a decor catalog) |
| 3 | Bytespider | ByteDance | yes | allow unless it causes load problems (repo says block; no evidence of harm for RR) |

## Agent-readiness checks geo-seo-claude added in 2026, and where RR stands (2026-10-14)

| Check | Repo's treatment | RR status | Action |
|---|---|---|---|
| `Content-Signal:` in robots.txt (IETF draft `draft-romm-aipref-contentsignals`) | non-scoring recommendation | absent | none for now. Only possible via `robots.txt.liquid`. A decor store wants `search=yes, ai-input=yes`, which is already the default behaviour, so adding it changes nothing. Re-check when the draft is final. |
| Cloudflare *managed* robots.txt blocking AI bots | flag | not present (Shopify sits behind Cloudflare, but no managed block is prepended) | keep checking every scan: Shopify could switch it on platform-wide |
| Markdown content negotiation (`Accept: text/markdown`) | pass if Content-Type is markdown | **misleading.** The homepage returns HTML labelled `text/markdown`. PDPs and collections return **404** to a strict markdown-only Accept and normal HTML when the header includes an HTML fallback | platform behaviour, not fixable in the theme. The repo's check (Content-Type only) would score this a false PASS; `bot_view.py` checks the body. Watch item. |
| RFC 8288 `Link:` header | informational | present, `rel="ucp"` → `/.well-known/ucp` (Shopify agentic commerce) | none |
| `/llms.txt` | 0-100 score, generator | present, Shopify-generated **agent-commerce instructions** (UCP/MCP + Shop skill), not a content map | none. Google says it does not use llms.txt; RR's 2026-07-10 audit already ruled it out as a lever. Do not overwrite Shopify's file. |

## Spoofed-UA caveat
`bot_view.py` sends each bot's user-agent from Eric's machine, not from the bot's IP range. A CDN that verifies bots by IP / reverse DNS can answer a spoof differently from the real crawler. A 200 is good evidence; a 403/429 must be confirmed in Bing Webmaster Tools (Crawl information) or GSC (Settings → Crawl stats) before anyone changes anything.
