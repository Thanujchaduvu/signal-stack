# Technical documentation (Signal Stack)

## 1. Architecture
Single FastAPI process: REST API + static dashboard + in-process APScheduler. SQLite stores companies, interview, competitors, sources, crawls (history), records (evidence), briefs, actions, job_runs, stack_changes, settings. Chosen for zero-ops reproducibility; swap the `db.py` helpers for Postgres if scaling.
Pipeline: `research → interview → profile → discovery → crawl → analysis/ranking → brief`, with `audit` and `reassess` as maintenance loops.

## 2. Source discovery (no hard-coded lists)
The LLM receives the research + founder profile and *proposes* competitors (5-10, incl. substitutes), customer-voice queries, market/regulatory topics and authorities, each with a company-specific reason. Proposals are then **verified against the real web**: a competitor needs a resolvable official site (search + fetch); every source is test-fetched (feed has entries / page has readable text / search returns results). Failures are dropped and reported. Sources land as `proposed`; the founder approves, adds or removes. Sources cover competitors (site-change, news, reviews/complaints), customers (forum/community search, HN), market (Google News topics, official bodies' pages) and internal (uploads).

## 3. Crawling and monitoring
`fetch.py` enforces robots.txt for HTML, per-domain delay, identifiable UA, timeouts; no authentication or paywall bypass. Kinds: RSS, HN API, search, page. Pages: first visit stores a baseline hash/snapshot; later visits diff added lines and emit a "Page changed" record. Dedupe: normalised URL key (tracking params and `www` stripped) plus order-insensitive title-token key. Every visit writes a `crawls` row (seen/new/dup, error). Failures increment `fail_count` (≥3 = dead).

## 4. Analysis and ranking
Each new record is analysed in batches against the profile: relevance gate (generic news excluded), event type, *what happened* (source-only), *why it matters* (interpretation, stored separately), impact type, urgency. Three independent measures: **source reliability** (domain class heuristics: government/edu, major press, primary source, forums), **evidence strength** (date present, snippet substance, primary source, independent corroboration count), **strategic relevance** (LLM 0-10 vs profile). LLM confidence is never used as truth; `verification` is rule-derived (verified / single-source / anecdotal / unverified / internal-data). Rank = 100 × Σ weight×component with weights relevance .25, impact .20, urgency .15, credibility .15, recency .15 (14-day decay), novelty .10 (1 − max title similarity to history); the explanation string lists top drivers.

## 5. Brief generation and integrity
Top records in the window are passed with ids; the model must cite ids. A validator removes any item without a valid id, so unsupported claims cannot reach the report. Empty sections state "no meaningful developments"; fewer-than-three opportunities is stated rather than padded. Appendix lists source, link, published/discovered dates, snippet, verification and the three scores. Exports: Markdown and email-ready HTML. Actions are tracked (open / in progress / done / dismissed).

## 6. Scheduling and reliability
APScheduler jobs per company: weekly brief (day/time/timezone from settings), monitoring interval, monthly audit. `job_runs` logs start/finish/status/traceback; failures show in *Settings & jobs*; runs left "running" at restart are marked failed. Manual triggers for all jobs. Audit flags dead URLs, inactive (>60d), declining relevance (<10% relevant over ≥5 items), duplicates, proposes new sources, and saves a report. `reassess` re-scores sources after context changes, retires stale ones with reasons, adds new ones, and stores a diff.

## 7. Internal intelligence
CSV/Excel/PDF/TXT → text chunks (max 6 per file on free tiers) → extraction of objections, lost-deal reasons, product requests, sales patterns, risks. Quotes must appear verbatim in the file or are dropped.
