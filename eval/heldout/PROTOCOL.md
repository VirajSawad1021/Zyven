# Held-out compile study: protocol

Written and committed on 2026-11-16, before any library below was compiled or any task was written. Changes after
this commit go in [Deviations](#7-deviations), with a date and a reason. The study answers one question:

> On popular libraries Zyven was never developed against, do compiled and gated tools help a model, and how do they
> compare with simply giving the model the library and a Python interpreter?

## 1. Hypotheses

| | Claim | Comparison |
|---|---|---|
| H1 | Compiled skills raise accuracy over the model alone | C4 vs C1 |
| H2 (primary) | Compiled skills are at least as accurate as the model with the library and an interpreter | C4 vs C3 |
| H3 | Tools that pass the gates are correct on held-out inputs (per-tool correctness, as in EvolveTool-Bench) | per tool |
| H4 | The differential gate is the one that stops most wrong tools | gate ablation |

H2 is the one that decides how the project describes itself. If C4 is clearly below C3, Zyven's claim becomes "a
correctness gate for tools", not "better answers", and the README says so (plan, checkpoint B).

## 2. Libraries

**Population.** The 3,000 most-downloaded PyPI projects over 30 days, as published by
[hugovk/top-pypi-packages](https://hugovk.github.io/top-pypi-packages/) on 2026-11-01
(`top-pypi-packages-2026-11-01.json`, trimmed to those 3,000 rows).

**Automatic rule** (`select_libraries.py`; outcome per project in `candidates.json`). A project is a candidate when:

| | Rule |
|---|---|
| A1 | it is not one Zyven was developed or evaluated against, or proposed for its catalog (python-stdnum, nepali, hijridate, pyluach, phonenumbers, sympy, mpmath, packaging, networkx, sqlglot) |
| A2 | its name is not a plugin, framework or cloud SDK pattern (`pytest-`, `django`, `azure-`, ...) |
| A4 | it has a classifier in Scientific/Engineering, Text Processing, Office/Business, Localization or Internationalization |
| A5 | it has no classifier in Internet, System, Database, Communications, build, testing, code generation, debugging, multimedia, desktop or security |
| A6 | its latest release has a pure-Python wheel |
| A7 | it does not require numpy, scipy, pandas, torch, tensorflow, jax, scikit-learn, matplotlib, pyarrow or polars |
| A8 | it states a license |

Result: 169 candidates.

**Reviewed rule** (`review.json`). Candidates are read in download-rank order. One is excluded only for one of these
reasons, written before the review:

| | Excluded when |
|---|---|
| R1 | it is not a library of functions that compute an answer from plain values (framework, service SDK, ML or data infrastructure, concurrency, object serialisation, configuration, plotting) |
| R1b | its interface is building objects in Python code (a grammar, a query, a data structure), so a tool would have to accept code |
| R2 | its main inputs or outputs are files or binary data |
| R3 | it needs an external program, a network service or downloaded data when used |
| R4 | it duplicates, forks, renames or plugs into a higher-ranked candidate |
| R5 | its answer depends on the current time or environment, or is a model's prediction |

The review stopped at the 40th accepted candidate (rank 1,470). The first 20 accepted are the **study set**; the next
20 are the **reserve set**, used only to extend the study to 40 libraries, in this order.

Study set: pygments, markdown-it-py, beautifulsoup4, wcwidth, docstring-parser, defusedxml, ruamel-yaml, docutils,
babel, tinycss2, xmltodict, lark, text-unidecode, mistune, humanize, boolean-py, prettytable, pyphen,
langchain-text-splitters, pycountry.

Reserve set: tinyhtml5, rfc3987-syntax, holidays, strictyaml, html5lib, inflect, pytimeparse, texttable, natsort,
feedparser, chevron, jsonpath-python, geographiclib, colorclass, num2words, ebcdic, parsimonious, markdown2,
pylatexenc, elementpath.

**No replacement.** A library that cannot be cloned, installed in the sandbox or compiled stays in the study and counts
as a compile failure. The study set is skewed towards text and markup processing because that is what popular
pure-Python libraries are; the paper reports that, it does not correct for it.

## 3. Compiling

- Each library is pinned to the commit of its latest release tag on the day its compile starts, and added to
  `catalog/repos.json` with that commit.
- The Scout picks the capability. No human chooses, edits or retries a capability. Everything the Scout proposes is
  recorded.
- One compile per library, with the default repair budget, for each of two compile setups: the open model in `.env`
  (`gemma-4-26b-a4b-it`), and one coding agent (Codex) as all roles. The Tester always comes from a different model
  family than the Compiler when both are configured.
- Every attempt is kept: `_failed_<name>/` for failures, with the gate that stopped it.
- No change to Zyven's code during the compile phase. A bug fix that is unavoidable is a deviation, and every compile
  before it is rerun.

## 4. Tasks

- **Written before the compile, without seeing any compiled tool.** For each library, 10 tasks from its public
  documentation (README and API reference), covering its main documented functions, not the capability the Scout will
  later choose. A task the compiled skill does not cover is a real miss and is counted.
- Tasks are written by a model session that has no access to Zyven's compile output, then read by a person for
  clarity only (wording, not difficulty).
- **Every expected answer is computed by calling the library** at the pinned commit, by a script committed with the
  tasks. A task whose answer cannot be computed this way is dropped before the run, and the drop is listed.
- Answers are scored by exact match after the normalisation each library's task file states (whitespace, case, JSON
  key order), fixed before the run.
- The task files and their SHA-256 hashes are committed before the first compile.

## 5. Conditions and runs

| | Condition | Tools |
|---|---|---|
| C1 | model alone | none |
| C2 | model with a Python interpreter | sandboxed Python, standard library only |
| C3 | model with the library and an interpreter | sandboxed Python with the library installed at the pinned commit |
| C4 | model with Zyven-compiled skills | the verified tools of that library's compile; no interpreter |

- Answering model: `gemma-4-26b-a4b-it` in all conditions, same output budget (8,192 tokens per call), same system
  prompt apart from the tool list.
- Three seeds per condition. Tasks in random order per seed.
- A library whose compile produced no verified tool runs C4 with no tools, and that is counted, not skipped.
- C2 and C3 use the interpreter harness from PR #35 once it is merged; until then they are not run.

## 6. Measures and analysis

- **Accuracy** per condition: mean over tasks, then over seeds.
- **Primary analysis (H2):** the difference C4 minus C3, with a 95% confidence interval from a bootstrap that
  resamples libraries (tasks within a library are not independent). H1 the same way for C4 minus C1. No p-value
  hunting: these two intervals are the result.
- **Compile outcomes:** share of libraries with at least one verified tool; for failures, the gate that stopped them.
- **Per-tool correctness (H3):** for every verified tool, 20 inputs drawn from its schema with Hypothesis, compared
  with the library called directly. Reported as the share of tools with correctness 1.0, and the mean.
- **Gate ablation (H4):** rerun the gates on every compile attempt's last adapter with one gate removed at a time, and
  count wrong tools (by the per-tool check) that would then have shipped.
- **Cost:** model tokens and wall time per compile and per task, per condition.
- All raw records go in `eval/results/heldout/`.

**Stopping and reporting.** The study set is run in full before any result is looked at per library. Results are
reported whatever they show, including a null or negative H2. Extension to the reserve set is decided in advance:
it happens if the study-set interval for H2 is wider than 20 points.

## 7. Deviations

None yet. Each entry: date, what changed, why, and which results it affects.
