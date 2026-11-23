# `zyven verify` on published attacks and on the official MCP servers (2026-11-23)

Two questions: does `zyven verify` catch the tool-poisoning attacks that security researchers have published, and does
it stay quiet on real, widely used servers?

## Published attack servers: 3 of 3 caught

Source: [invariantlabs-ai/mcp-injection-experiments](https://github.com/invariantlabs-ai/mcp-injection-experiments)
at `7382a5e`, the proof-of-concept servers published with Invariant Labs' tool-poisoning research. Each was run in
Zyven's sandbox (no network, read-only root, no capabilities, non-root) with `--probe`.

| Server | What it does | Verdict | What `verify` reports |
|---|---|---|---|
| `direct-poisoning.py` | Hidden instructions to read `~/.cursor/mcp.json` and an SSH key and pass them in a parameter | **FAIL** | hidden instruction block; "do something else first"; names a config file; asks the model to hide it from the user |
| `shadowing.py` | A harmless `add` tool whose description tells the model to send every email from *another* tool to the attacker | **FAIL** | tool shadowing ("side effect on the also present send_email tool"); redirects messages to a fixed address; hidden instruction block; hiding from the user |
| `whatsapp-takeover.py` | A rug pull: a harmless "fact of the day" tool that, from its second start on, rewrites its description to redirect WhatsApp messages to the attacker's number | **FAIL** against the lock file | stability: definitions differ from the lock file and the server renamed itself; descriptions: tool shadowing, redirects messages to a fixed number, hiding from the user, hidden instruction block |

The rug pull, step by step:

1. Day 1: `zyven verify --lock whatsapp.lock.json -- python whatsapp-takeover.py`. The server looks harmless, PASS,
   and its tool definitions are recorded in the lock file.
2. Day 2: the same command. The server has switched to its attack description: **FAIL**, the definitions differ
   from the lock file and four suspicious passages are named.

The server switches when a marker file exists, which it creates with the Unix `touch` command. On Windows, where this
was run, the marker was created by hand to start day 2. In the sandbox the switch never happens at all: every start
is a fresh container, so the server never gets to remember its first run.

## Official reference servers: 7 of 7 pass

From [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers), installed from npm and PyPI
into sandbox images and checked with `--probe`:

| Server | Version | Tools | Verdict | Notes |
|---|---|---|---|---|
| filesystem | 1.0.0 | 14 | PASS | some parameters have no description |
| memory | 1.0.0 | 9 | PASS | some parameters have no description |
| sequential-thinking | 1.0.0 | 1 | PASS | its description is 2,781 characters (flagged as long, to read) |
| everything | 1.0.0 | 13 | PASS | one parameter has no description |
| fetch | 2026.11.18 | 1 | PASS | |
| git | 2026.11.18 | 14 | PASS | some parameters have no description |
| time | 2026.11.18 | 3 | PASS | |

55 tools; no failed check on any server. The notes are warnings, not failures.

## Reproduce

```bash
git clone https://github.com/invariantlabs-ai/mcp-injection-experiments
# an image with the MCP SDK 1.x the examples use:  FROM python:3.12-slim / RUN pip install "mcp[cli]>=1.6,<2"
zyven verify --docker <that image> --mount ./mcp-injection-experiments:/work --probe -- mcp run /work/shadowing.py
zyven verify --docker <image with the reference servers> --probe -- mcp-server-git --repository /work
```
