# Cost statement: all free / open source
| Component | Cost | Limitation |
|---|---|---|
| FastAPI, SQLite, APScheduler, httpx, trafilatura, feedparser, pandas, pypdf, markdown | $0 (OSS) | none |
| `ddgs` (DuckDuckGo metasearch library) | $0, no key | unofficial; can throttle/return empty → discovery drops unverifiable candidates |
| Google News RSS, Hacker News Algolia API | $0, no key | public feeds; RSS items limited (~20/query); Google News links are redirect URLs |
| LLM: Gemini free tier **or** Groq free tier **or** local Ollama | $0 | Free-tier requests/min and daily caps; the client retries with backoff. Ollama has no caps but needs local hardware |
| Hosting | $0 locally; any free container host works with the Dockerfile | free hosts may sleep (scheduler only runs while the process is up) and may have ephemeral disk: mount `data/` |
No paid APIs, scraping platforms or AI services are used.
Typical usage per company: ≈30 LLM calls for stack discovery, ≈1 per 8 collected items for analysis, 1 for the brief.
