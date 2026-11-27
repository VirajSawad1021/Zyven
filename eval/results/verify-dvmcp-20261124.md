# `zyven verify` on Damn Vulnerable MCP Server (2026-11-24)

[Damn Vulnerable MCP Server](https://github.com/harishsg993010/damn-vulnerable-MCP-server) at `cdc4c6b` has 15
deliberately vulnerable MCP servers. Each was run in Zyven's sandbox (no network, read-only root, no capabilities,
non-root) with:

```bash
zyven verify --docker <image with the project's requirements> --mount ./damn-vulnerable-MCP-server:/work \
  --probe --call all -- sh -c "cd /work && PYTHONPATH=/work exec mcp run challenges/<group>/<challenge>/server.py"
```

`--call all` calls every tool four times with valid sample input taken from its schema, reads what comes back, and
lists the tools again afterwards.

**7 of 15 fail. 3 more list the exact risky capability.**

| # | Challenge | Verdict | What `verify` reports |
|---|---|---|---|
| 2 | Tool poisoning | **FAIL** | descriptions: hidden instruction block, hiding from the user |
| 4 | Rug pull | **FAIL** | results: after three calls, `get_weather` and `get_news` start returning `<IMPORTANT>` instruction blocks |
| 5 | Tool shadowing | **FAIL** | descriptions: hidden instructions in the shadowing tools |
| 6 | Indirect prompt injection | **FAIL** | results: a stored document returned by `search_documents` carries a `<!-- SYSTEM INSTRUCTION ... -->` comment |
| 7 | Token theft | **FAIL** | results: three tools return a JSON Web Token and an API key (masked in the report) |
| 10 | Multi-vector attack | **FAIL** | descriptions: hidden instruction block in `get_user_profile`; results: `authenticate_user` returns a token |
| 11 | JWT claim forgery | **FAIL** | results: `get_server_config` returns the JWT signing secret |
| 3 | Excessive permission scope | capability | `read_file`, `list_directory`, `search_files`: reads files at a path the caller chooses |
| 8 | Malicious code execution | capability | `execute_code`: runs code it is given; `run_command`: runs shell commands |
| 9 | Remote access control | capability | `network_diagnostic`: runs shell commands; four tools contact a host the caller chooses |
| 1 | Basic prompt injection | not flagged | the attacker is the user typing into the tool; the server itself returns nothing malicious |
| 12 | Hidden identity override | not flagged | an authorization bug (another user's record through an undocumented parameter) |
| 13 | Workflow IDOR | not flagged | an authorization bug across a multi-step workflow |
| 14 | Marketplace plugin poisoning | not flagged | the malicious plugin loads only when a specific plugin name is chosen |
| 15 | Dependency confusion | not flagged | the malicious package installs only after a specific sequence of calls |

The five not flagged are logic bugs that show up only with particular users, names or call sequences, not with
sample input. Capabilities are listed, not counted as failures: a file or shell tool is legitimate in many servers,
and the reader decides whether it belongs. A credential in a tool's output fails the results check even when the tool
is a login that returns a token by design (as in challenge 10): the model reads that token either way, so the report
names it, masked, for the reader to judge.

## No false alarms on the official servers

With the same `--probe --call all`, the seven official reference servers (filesystem, memory, sequential-thinking,
everything, fetch, git, time) pass: all 55 tools were called, 146 responses read, nothing flagged.
