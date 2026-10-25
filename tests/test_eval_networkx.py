"""The networkx task suite: deterministic, well-formed, and its answers hold when recomputed a different way."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

nx = pytest.importorskip("networkx")  # 3.7 needs Python 3.12+

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval import tasks_networkx as T  # noqa: E402


def _by_cat(tasks):
    out: dict[str, list] = {}
    for t in tasks:
        out.setdefault(t.category, []).append(t)
    return out


def test_generation_is_deterministic_and_covers_every_category():
    a, b = T.generate(per_category=4, seed=7), T.generate(per_category=4, seed=7)
    assert [(t.id, t.question, t.expected) for t in a] == [(t.id, t.question, t.expected) for t in b]
    assert [(t.question) for t in T.generate(per_category=4, seed=8)] != [t.question for t in a]
    assert set(_by_cat(a)) == {"shortest_path", "components", "mst_weight", "max_flow", "betweenness_top", "triangle_count"}
    assert all(len(v) == 4 for v in _by_cat(a).values())


def test_each_expected_answer_scores_true_and_a_wrong_one_scores_false():
    for t in T.generate(per_category=6):
        assert T.score(t, t.expected), t.id
        wrong = "B" if t.expected == "A" else "A" if not t.expected.isdigit() else str(int(t.expected) + 1)
        assert not T.score(t, wrong), t.id


def test_the_answer_must_be_exactly_one_value_not_prose_or_several_values():
    nodes = next(t for t in T.generate(per_category=1) if t.category == "betweenness_top")
    ints = next(t for t in T.generate(per_category=1) if t.category == "shortest_path")
    e = ints.expected
    wrong = str(int(e) + 1)
    for reply in (e, f"{e}.", f"**{e}**", f"`{e}`", f"  {e}  "):
        assert T.score(ints, reply), reply
    for reply in ("I cannot tell", "", f"The shortest path has total weight {e}", f"{wrong}; actually {e}", f"{e} or {wrong}",
                  f"Path A-B-C costs 3+4, so {e}", f"{e}.5"):
        assert not T.score(ints, reply), reply  # prose, several values, or a decimal: not one integer
    e = nodes.expected
    other = "B" if e != "B" else "C"
    for reply in (e, f"**{e}**", f"Node {e}", f"{e}.", f"`{e}`"):
        assert T.score(nodes, reply), reply
    for reply in ("no idea", f"The top node is {e}.", f"I think {e}", f"{e} or {other}", f"{other}, while {e} is close", f"{other}"):
        assert not T.score(nodes, reply), reply


def _edges(q: str, weighted: bool, directed: bool):
    arrow = "->" if directed else "-"
    pat = rf"([A-Za-z0-9]+){re.escape(arrow)}([A-Za-z0-9]+)" + (r":(\d+)" if weighted else "")
    return [m for m in re.findall(pat, q)]


def test_answers_survive_rebuilding_each_graph_from_the_question_text_and_using_another_algorithm():
    for t in T.generate(per_category=8, seed=11):
        q = t.question
        if t.category == "shortest_path":
            G = nx.Graph()
            G.add_weighted_edges_from((u, v, int(w)) for u, v, w in _edges(q.split("What is")[0], True, False))
            s, d = re.findall(r"from ([A-L]) to ([A-L])\?", q)[0]
            assert str(nx.shortest_path_length(G, s, d, weight="weight", method="bellman-ford")) == t.expected, q
        elif t.category == "components":
            G = nx.Graph()
            G.add_nodes_from(f"n{i}" for i in range(1, 17))
            G.add_edges_from(_edges(q.split("Nodes that")[0], False, False))
            assert str(sum(1 for _ in nx.connected_components(G))) == t.expected, q
        elif t.category == "mst_weight":
            G = nx.Graph()
            G.add_weighted_edges_from((u, v, int(w)) for u, v, w in _edges(q.split("What is")[0], True, False))
            assert str(sum(d["weight"] for *_, d in nx.minimum_spanning_edges(G, algorithm="prim", data=True))) == t.expected, q
        elif t.category == "max_flow":
            G = nx.DiGraph()
            for u, v, c in _edges(q.split("What is")[0], True, True):
                G.add_edge(u, v, capacity=int(c))
            s, d = re.findall(r"flow from ([A-L]) to ([A-L])\?", q)[0]
            assert str(nx.maximum_flow_value(G, s, d, flow_func=nx.algorithms.flow.preflow_push)) == t.expected, q
        elif t.category == "betweenness_top":
            G = nx.Graph(_edges(q.split("Which node")[0], False, False))
            ranked = sorted(nx.betweenness_centrality(G, normalized=False).items(), key=lambda kv: -kv[1])
            assert ranked[0][0] == t.expected and ranked[0][1] > ranked[1][1], q  # unique top, however it is normalised
        elif t.category == "triangle_count":
            import itertools
            G = nx.Graph(_edges(q.split("How many")[0], False, False))
            brute = sum(1 for a, b, c in itertools.combinations(G.nodes, 3) if G.has_edge(a, b) and G.has_edge(b, c) and G.has_edge(a, c))
            assert str(brute) == t.expected, q
