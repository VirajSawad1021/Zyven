"""Model families per role, and how independent the Tester is from the Compiler."""

from zyven.ai.families import family_of
from zyven.ai.families import tester_independence as independence  # a "test" prefix would be collected


def test_families_from_provider_labels():
    assert family_of("gemma-4-26b-a4b-it@generativelanguage.googleapis.com") == "google"
    assert family_of("gpt-5.1@api.openai.com [closed model]") == "openai"
    assert family_of("Qwen3.8-Flash@dashscope") == "alibaba"
    assert family_of("Codex (gpt-5.1-codex) [coding agent]") == "openai"
    assert family_of("Codex (its default model) [coding agent]") == "openai"       # the agent's maker
    assert family_of("Claude Code (its default model) [coding agent]") == "anthropic"
    assert family_of("OpenCode (its default model) [coding agent]") == "unknown"   # many providers behind it
    assert family_of("OpenCode (deepseek-v3.2) [coding agent]") == "deepseek"
    assert family_of("gemma-4-31b-it@host (fallback llama-3.3-70b@host)") == "google"  # the main model counts


def test_tester_independence():
    g26, g31 = "gemma-4-26b-a4b-it@g", "gemma-4-31b-it@g"
    assert independence({"compiler": g26, "tester": g26}) == "same model"
    assert independence({"compiler": g26, "tester": g31}) == "same family"
    assert independence({"compiler": g26, "tester": "Codex (gpt-5.1) [coding agent]"}) == "different family"
    assert independence({"compiler": g26, "tester": "OpenCode (its default model) [coding agent]"}) == "unknown"
