"""Which model family wrote what, so a compile can say how independent its Tester was.

The differential gate compares a tool with the library through reference calls the Tester writes. If the Tester and
the Compiler misread the library the same way, a wrong tool can pass. Errors are more alike between models of the same
family (Kim et al., "Correlated Errors in Large Language Models", ICML 2025), so a compile records whether its Tester
came from a different family than its Compiler, and warns when it did not.
"""

from __future__ import annotations

import re

# (pattern in a provider label, family). The model name is matched first; a coding agent with its default model
# falls back to the agent's maker.
_MODEL_FAMILIES = [
    (r"\bgemma|\bgemini", "google"),
    (r"\bgpt-|\bo[1-9]\b|\bo[1-9]-|codex-mini|\bchatgpt", "openai"),
    (r"\bclaude|\bopus\b|\bsonnet\b|\bhaiku\b|\bfable\b|\bmythos\b", "anthropic"),
    (r"\bqwen", "alibaba"),
    (r"\bllama", "meta"),
    (r"\bmistral|\bmixtral|\bcodestral|\bdevstral|\bmagistral", "mistral"),
    (r"\bdeepseek", "deepseek"),
    (r"\bkimi|\bmoonshot", "moonshot"),
    (r"\bglm|\bzhipu", "zhipu"),
    (r"\bgrok", "xai"),
    (r"\bphi-?\d", "microsoft"),
    (r"\bnemotron", "nvidia"),
]
_AGENT_MAKERS = [(r"^codex\b", "openai"), (r"^claude code\b", "anthropic"), (r"^antigravity\b", "google")]


def family_of(label: str) -> str:
    """The model family behind a provider label, or "unknown"."""
    text = (label or "").lower()
    model = re.sub(r"@.*$", "", text.split(" (fallback")[0])  # "gemma-4-31b-it@host [closed model]" -> the model
    paren = re.search(r"\(([^)]*)\)", text)  # "Codex (gpt-5.1) [coding agent]" -> "gpt-5.1"
    for candidate in ([paren.group(1)] if paren and "[coding agent]" in text else []) + [model]:
        for rx, fam in _MODEL_FAMILIES:
            if re.search(rx, candidate):
                return fam
    for rx, fam in _AGENT_MAKERS:
        if re.search(rx, text):
            return fam
    return "unknown"


def tester_independence(roles: dict[str, str]) -> str:
    """How independent the Tester's reference calls are from the Compiler's code: "same model", "same family",
    "different family", or "unknown" when either family cannot be told from its label."""
    tester, compiler = roles.get("tester", ""), roles.get("compiler", "")
    if tester and tester == compiler:
        return "same model"
    ft, fc = family_of(tester), family_of(compiler)
    if "unknown" in (ft, fc):
        return "unknown"
    return "same family" if ft == fc else "different family"
