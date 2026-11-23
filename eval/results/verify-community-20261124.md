# `zyven verify` on 23 popular community MCP servers (2026-11-24)

Each server was installed from npm or PyPI into a sandbox image and checked with:

```bash
zyven verify --docker <image> --probe --call read-only -- <server command>
```

The sandbox has no network unless a run says otherwise, a read-only root, no capabilities and a non-root user.
Servers that refuse to start without an API key got an obviously fake one (`dummy-not-a-real-key`); none can reach
its service from the sandbox. `--call read-only` calls only the tools that declare `readOnlyHint`, four times each, with
sample input from their schemas.

**22 of the 23 servers started. 21 of those pass; one fails a robustness check.**

| Server | Package and version | Tools | Called | Verdict | Notes |
|---|---|---|---|---|---|
| Playwright | `@playwright/mcp` 0.0.86 | 25 | 7 | PASS | |
| Sentry | `@sentry/mcp-server` 0.50.0 | 74 | 19 | PASS | |
| Firecrawl | `firecrawl-mcp` 3.41.0 | 34 | 23 | PASS | one long description |
| Notion | `@notionhq/notion-mcp-server` 2.6.1 | 24 | 12 | PASS | |
| Heroku | `@heroku/mcp-server` 1.2.15 | 33 | 0 | PASS | no tool declares read-only |
| Kubernetes | `mcp-server-kubernetes` 4.2.3 | 23 | 6 | PASS | |
| Chart (AntV) | `@antv/mcp-server-chart` 0.9.10 | 27 | 27 | PASS | |
| Brave Search | `@brave/brave-search-mcp-server` 2.2.0 | 9 | 9 | PASS | |
| Browserbase | `@browserbasehq/mcp-server-browserbase` 2.4.3 | 9 | 0 | PASS | |
| Exa | `exa-mcp-server` 3.5.1 | 3 | 3 | PASS | |
| Tavily | `tavily-mcp` 0.2.22 | 5 | 0 | PASS | |
| Context7 | `@upstash/context7-mcp` 4.7.3 | 2 | 2 | PASS | one long description |
| arXiv | `arxiv-mcp-server` 0.8.2 | 19 | 11 | PASS | needs MCP SDK 1.x (see below) |
| AWS Documentation | `awslabs.aws-documentation-mcp-server` 1.2.6 | 5 | 0 | PASS | three long descriptions |
| DuckDuckGo | `duckduckgo-mcp-server` 0.7.0 | 3 | 0 | PASS | |
| MarkItDown | `markitdown-mcp` 0.0.1a8 | 1 | 0 | PASS | |
| Qdrant | `mcp-server-qdrant` 0.8.0 | 2 | 0 | PASS | network limited to Hugging Face (see below) |
| GitHub (reference, archived) | `@modelcontextprotocol/server-github` 2025.4.8 | 26 | 0 | PASS | |
| Puppeteer (reference, archived) | `@modelcontextprotocol/server-puppeteer` 2025.5.12 | 7 | 0 | PASS | |
| Google Maps (reference, archived) | `@modelcontextprotocol/server-google-maps` 0.6.2 | 7 | 0 | PASS | |
| Brave Search (reference, archived) | `@modelcontextprotocol/server-brave-search` 0.6.2 | 2 | 0 | PASS | |
| Slack (reference, archived) | `@modelcontextprotocol/server-slack` 2025.4.25 | 8 | 0 | FAIL | robustness: accepts calls with missing required parameters and wrong types (12 of 12) |
| Supabase | `@supabase/mcp-server-supabase` 0.19.0 | | | did not start | needs to reach Supabase with a real account at startup |

348 tools in all, 119 of them called with valid input. Most "PASS" rows also carry warnings, mostly parameters without
a description and tools that do not say whether they are read-only; those are listed in each report, not counted as
failures.

## What the checks showed besides the verdicts

- **Qdrant**, allowed to reach only Hugging Face (to download its embedding model), also tried to reach
  `mobile.events.data.microsoft.com` and `pypi.org`. The egress proxy refused both and the report names them.
- **arXiv** crashes at startup with the current MCP SDK 2.x (`'Server' object has no attribute 'list_prompts'`),
  because the package does not limit itself to SDK 1.x. Installed with `mcp<2`, it passes every check.
- **Firecrawl** first failed with a false alarm: its `alexandria_library_search` takes shell-style commands over a
  read-only file system, and the name-and-parameter rule read that as a read-only tool that runs commands. The rule
  now needs the tool's name to say it runs or writes something; the capability is still listed.

The Slack server is archived (no longer maintained), and the finding is about input validation, not an attack.
