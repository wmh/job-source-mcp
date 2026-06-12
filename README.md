# job-source-mcp

MCP server that searches job listings from Taiwanese job boards and returns normalized results.

**Supported sources:**
- [104](https://www.104.com.tw) — uses `curl_cffi` Chrome TLS impersonation; no login required
- [Yourator](https://www.yourator.co) — uses Playwright headless browser; no login required

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

Returns readiness of each source. Both sources work without login.

### `search_jobs`

Search job listings across one or both sources.

```json
{
  "keyword": "golang backend",
  "source": "all",
  "page": 1,
  "limit": 20,
  "location": "台北市"
}
```

`source` accepts: `"all"`, `"104"`, `"yourator"`.

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
  "errors": []
}
```

## How it works

**104** — Direct API call to `https://www.104.com.tw/jobs/search/api/jobs` using `curl_cffi` with `impersonate="chrome110"`. This bypasses Cloudflare bot detection by presenting a real Chrome TLS fingerprint. No login or session cookie required.

**Yourator** — Playwright launches a headless Chromium browser, navigates to `https://www.yourator.co/jobs?term=<keyword>`, and intercepts the backend API response (`GET /api/v4/jobs?term=<keyword>`). The browser's persistent profile is stored in `~/.config/job-source-mcp/profiles/yourator/` so it is reused across runs.

If `browser-cookie3` is installed, Yourator also injects cookies from your local Chrome profile, which may improve result relevance for logged-in users.

## Configuration

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `JOB_SOURCE_DIR` | `~/.config/job-source-mcp` | Base directory for Playwright browser profiles |

## Rate limiting

Both adapters include a random delay (1.5–4 s) per request to simulate human browsing speed. When searching multiple keywords, call `search_jobs` sequentially rather than in parallel.

## License

[MIT](LICENSE)
