"""A least-privilege settings file for Anthropic's sandbox-runtime (srt), from what `zyven verify` observed.

Only hosts the server reached during the check are allowed, nothing may be written, and common credential folders may
not be read. The check makes only a few calls, so a server can need more hosts in real use: add them by hand after
reading why.
"""

from __future__ import annotations

from typing import Any

from zyven.mcpverify.checks import Report

CREDENTIAL_DIRS = ["~/.ssh", "~/.aws", "~/.gnupg", "~/.azure", "~/.kube", "~/.docker", "~/.config/gcloud",
                   "~/.config/gh", "~/.netrc", "~/.npmrc", "~/.pypirc"]


def srt_settings(report: Report) -> dict[str, Any]:
    """The settings dict. Raises ValueError (with a message that says to run with --docker and --allow-host) when
    report.reached_hosts is None, i.e. no network observation was made."""
    if report.reached_hosts is None:
        raise ValueError("no network observation was made; run with --docker and --allow-host")
    return {
        "filesystem": {"denyRead": list(CREDENTIAL_DIRS), "allowWrite": [], "denyWrite": []},
        "network": {"allowedDomains": sorted(set(report.reached_hosts)), "deniedDomains": []},
    }
