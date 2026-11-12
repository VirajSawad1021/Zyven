# Security policy

Zyven runs code it did not write: compiled skills, and third-party MCP servers under `zyven verify`. A flaw in its
sandbox, its checks or its own release can put users at risk, so reports are welcome.

## Reporting a vulnerability

Please report it privately through GitHub: **Security → Report a vulnerability** on this repository. Do not open a
public issue for anything that could be exploited before a fix ships.

Useful to include:
- what an attacker controls (a skill's source, an MCP server, its tool descriptions, network responses)
- what they gain (escape from the sandbox, a check that passes when it should fail, code run on the host)
- the smallest steps or server that reproduce it

You should hear back within a week. A fix and a credited advisory follow once it is confirmed.

## In scope

- Escaping the Docker sandbox, or reaching the network beyond the egress allowlist (`--allow-host`).
- A `zyven verify` check that a malicious server can pass, such as poisoning it misses, a rug pull the lock file does
  not catch, or a crash of Zyven itself.
- A compiled skill passing the gates while behaving differently from its library in a way the gates claim to check.
- The board or `zyven mcp` acting on input from a tool result, page or model as if it came from the user.
- Zyven's own supply chain: its workflows, its GitHub Action and its PyPI releases.

## Not in scope

- Running a skill or server with `ZYVEN_SKILL_RUNTIME=host` or `zyven verify` without `--docker`. That runs code on the
  host by design. See [LIMITATIONS.md](LIMITATIONS.md).
- Weaknesses that need an attacker who already controls the machine or its Docker daemon.

## Releases

Releases are built by `.github/workflows/release.yml` from a version tag and published with PyPI trusted publishing. No
token is stored in the repository, and every file carries a signed PEP 740 attestation. All actions are pinned to
commit SHAs.
