# job-source-mcp

MCP server that searches job listings from Taiwanese job boards and returns normalized results.

**Supported sources:**
- [104](https://www.104.com.tw) — uses `curl_cffi` Chrome TLS impersonation; no login required
- [Yourator](https://www.yourator.co) — uses Playwright headless browser; no login required
- [CakeResume](https://www.cakeresume.com) — uses `curl_cffi` Chrome TLS impersonation; no login required
- [LinkedIn](https://www.linkedin.com/jobs) — uses the public guest job-search API via `curl_cffi`; no login required

> **Removed source:** Meet.jobs was supported until the service permanently shut
> down on 2026-06-30 (the site now serves only a closure announcement). The
> adapter was removed in July 2026.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

To also enable Chrome cookie injection for Yourator (improves result quality on accounts with browsing history):

```bash
pip install -e ".[cookies]"
```

## Usage with Claude Code

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "job-source": {
      "type": "stdio",
      "command": "/path/to/.venv/bin/job-source-mcp"
    }
  }
}
```

## MCP tools

### `ping`

Health check. Returns `{"ok": true}`.

### `session_status`

Returns readiness of each source. All sources work without login.

### `search_jobs`

Search job listings across one or more sources.

```json
{
  "keyword": "golang backend",
  "source": "all",
  "page": 1,
  "limit": 20,
  "location": "台北市"
}
```

`source` accepts: `"all"`, `"104"`, `"yourator"`, `"cakeresume"`, `"linkedin"`.

**Response:**

```json
{
  "keyword": "golang backend",
  "source": "all",
  "count": 12,
  "jobs": [
    {
      "source": "104",
      "id": "abc123",
      "title": "Golang Backend Engineer",
      "company": "Acme Corp",
      "location": "台北市信義區",
      "salary": "80,000–120,000",
      "url": "https://www.104.com.tw/job/abc123",
      "posted_at": "20260601",
      "tags": ["Go", "Kafka", "Redis"],
      "description": "..."
    }
  ],
  "rate_limited": [],
  "errors": []
}
```

`rate_limited` lists any source that returned `HTTP 429` even after backing off (each entry: `{"source", "retry_after"}`). It exists so a throttled source is never confused with one that simply found nothing: if `count` is `0` **and** `rate_limited` is empty, the search genuinely matched no jobs; if a source appears in `rate_limited`, its `0` results mean "couldn't fetch", not "no matches". Rate-limited sources also appear in `errors` with `"type": "rate_limited"` (other failures use `"type": "error"`).

## How it works

**104** — Direct API call to `https://www.104.com.tw/jobs/search/api/jobs` using `curl_cffi` with `impersonate="chrome110"`. This bypasses Cloudflare bot detection by presenting a real Chrome TLS fingerprint. No login or session cookie required.

**Yourator** — Playwright launches a headless Chromium browser, navigates to `https://www.yourator.co/jobs?term=<keyword>`, and intercepts the backend API response (`GET /api/v4/jobs?term=<keyword>`). The browser's persistent profile is stored in `~/.config/job-source-mcp/profiles/yourator/` so it is reused across runs.

If `browser-cookie3` is installed, Yourator also injects cookies from your local Chrome profile, which may improve result relevance for logged-in users.

**CakeResume** — Fetches the search results page `https://www.cakeresume.com/jobs?q=<keyword>` (filtered to `zh-TW`) with `curl_cffi` using `impersonate="chrome110"`, then parses the embedded Next.js `__NEXT_DATA__` JSON blob to extract listings. No login or session cookie required. CakeResume caps each page at ~10 results. Returned `url` uses the `cakeresume.com/jobs/<slug>` path; the canonical clickable form is `cake.me/companies/<company-slug>/jobs/<slug>`.

**LinkedIn** — Calls the public guest job-search endpoint `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search` with `curl_cffi` (`impersonate="chrome110"`) and parses the returned HTML job cards with BeautifulSoup. No login or session cookie required. Pagination uses an offset (`start = (page - 1) * 10`); each request yields ~10 cards. When `location` is omitted it defaults to `Taiwan`. Guest cards do not include a job description (left empty) and rarely include salary. LinkedIn is the most rate-limit-sensitive source, so requests use an **adaptive low-frequency limiter** (see Rate limiting).

## Configuration

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `JOB_SOURCE_DIR` | `~/.config/job-source-mcp` | Base directory for Playwright browser profiles |

## Rate limiting

The 104, Yourator, and CakeResume adapters include a random delay (1.5–4 s) per request to simulate human browsing speed.

LinkedIn uses an **adaptive process-wide rate limiter** (`job_source_mcp/throttle.py`). It serializes outbound requests with a minimum spacing (≥ 8 s, plus jitter) so the server never calls this API at high frequency. When a source returns `HTTP 429`, the limiter **escalates the interval and keeps it escalated** (doubling, up to 120 s for LinkedIn) and backs off before a single retry — the response to throttling is to call *less often*, not to retry harder. The interval only relaxes gradually after sustained success.

When searching multiple keywords, call `search_jobs` sequentially rather than in parallel.

## Development

Install with the dev extras, then run the linter and tests:

```bash
pip install -e ".[dev]"
ruff check .        # lint
pytest              # tests (no network access required)
```

The test suite mocks the network layer (`curl_cffi` sessions) and drives the
adapters' parsers with fixtures, so it runs offline in well under a second. CI
(`.github/workflows/ci.yml`) runs the same `ruff check` + `pytest` across Python
3.11–3.13 on every push and pull request.

## License

[MIT](LICENSE)
