"""Graph-algorithm task set: shortest paths, components, spanning trees, max flow, betweenness, triangles.

Ground truth is computed by NetworkX itself (pinned in catalog/repos.json), never by a model. Graphs are generated
from a seed, sized so that a model cannot reliably do them in its head, and every "which node is top" question is
checked to have a unique answer with a clear margin. Only algorithms that run on the standard library are used:
NetworkX's PageRank, for one, needs numpy, which a verified skill's sandbox does not have.
"""

from __future__ import annotations

import random
import re

import networkx as nx

from eval.tasks import Task

SYSTEM_HINT = ("Reply with only the final answer: a single integer, or a single node letter for 'which node' questions. "
               "Use the standard definitions of the algorithms.")

_NODES = "ABCDEFGHIJKL"


def _edge_list(edges, weighted: bool = False, directed: bool = False) -> str:
    arrow = "->" if directed else "-"
    return ", ".join(f"{u}{arrow}{v}:{w}" if weighted else f"{u}{arrow}{v}" for u, v, w in edges)


def _connected_weighted(rng: random.Random, n: int, extra: int, lo: int = 1, hi: int = 12):
    """A connected undirected weighted graph on n nodes: a random spanning tree plus `extra` more edges."""
    names = list(_NODES[:n])
    rng.shuffle(names)
    edges = {}
    for i in range(1, n):
        u, v = names[i], names[rng.randrange(i)]
        edges[tuple(sorted((u, v)))] = rng.randint(lo, hi)
    while extra > 0:
        u, v = sorted(rng.sample(names, 2))
        if (u, v) not in edges:
            edges[(u, v)] = rng.randint(lo, hi)
            extra -= 1
    return sorted((u, v, w) for (u, v), w in edges.items())


def _shortest_path(rng):
    edges = _connected_weighted(rng, 10, 8)
    G = nx.Graph()
    G.add_weighted_edges_from(edges)
    s, t = rng.sample(sorted(G.nodes), 2)
    q = (f"Undirected weighted graph, edges written node-node:weight: {_edge_list(edges, True)}. "
         f"What is the total weight of the shortest path from {s} to {t}?")
    return q, str(nx.dijkstra_path_length(G, s, t))


def _components(rng):
    n = 16
    nodes = [f"n{i}" for i in range(1, n + 1)]
    pairs = set()
    while len(pairs) < 9:
        u, v = sorted(rng.sample(nodes, 2), key=lambda x: int(x[1:]))
        pairs.add((u, v))
    edges = sorted(pairs, key=lambda e: (int(e[0][1:]), int(e[1][1:])))
    G = nx.Graph()
    G.add_nodes_from(nodes)
    G.add_edges_from(edges)
    q = (f"An undirected graph has the 16 nodes n1 to n16 and these edges: {', '.join(f'{u}-{v}' for u, v in edges)}. "
         "Nodes that appear in no edge are isolated. How many connected components does the graph have?")
    return q, str(nx.number_connected_components(G))


def _mst(rng):
    edges = _connected_weighted(rng, 9, 6, 1, 15)
    G = nx.Graph()
    G.add_weighted_edges_from(edges)
    q = (f"Undirected weighted graph, edges written node-node:weight: {_edge_list(edges, True)}. "
         "What is the total weight of a minimum spanning tree?")
    return q, str(int(nx.minimum_spanning_tree(G).size(weight="weight")))


def _max_flow(rng):
    names = list(_NODES[:8])
    edges = {}
    for i in range(1, 8):  # keep a chain S..T so that flow exists
        edges[(names[i - 1], names[i])] = rng.randint(2, 9)
    while len(edges) < 14:
        u, v = rng.sample(names, 2)
        if (u, v) not in edges and (v, u) not in edges and v != names[0] and u != names[-1]:
            edges[(u, v)] = rng.randint(2, 9)
    G = nx.DiGraph()
    for (u, v), c in edges.items():
        G.add_edge(u, v, capacity=c)
    listed = sorted((u, v, c) for (u, v), c in edges.items())
    q = (f"Directed graph with edge capacities, written from->to:capacity: {_edge_list(listed, True, True)}. "
         "Each arrow is the only direction that has capacity; a direction that is not listed has capacity 0. "
         f"What is the maximum flow from {names[0]} to {names[-1]}?")
    return q, str(nx.maximum_flow_value(G, names[0], names[-1]))


def _top_node(centrality, margin: float):
    ranked = sorted(centrality.items(), key=lambda kv: -kv[1])
    return ranked[0][0] if ranked[0][1] - ranked[1][1] > margin else None


def _betweenness(rng):
    while True:
        edges = _connected_weighted(rng, 10, 5)
        G = nx.Graph()
        G.add_edges_from((u, v) for u, v, _ in edges)
        top = _top_node(nx.betweenness_centrality(G), 0.02)
        if top:
            q = (f"Undirected unweighted graph with edges: {_edge_list([(u, v, 0) for u, v, _ in edges])}. "
                 "Which node has the highest betweenness centrality?")
            return q, top


def _triangles(rng):
    edges = _connected_weighted(rng, 10, 9)
    G = nx.Graph()
    G.add_edges_from((u, v) for u, v, _ in edges)
    q = (f"Undirected unweighted graph with edges: {_edge_list([(u, v, 0) for u, v, _ in edges])}. "
         "How many triangles (sets of three nodes that are all connected to each other) does it contain?")
    return q, str(sum(nx.triangles(G).values()) // 3)


_MAKERS = {"shortest_path": _shortest_path, "components": _components, "mst_weight": _mst, "max_flow": _max_flow,
           "betweenness_top": _betweenness, "triangle_count": _triangles}


def generate(per_category: int = 6, seed: int = 2026) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []
    for cat, make in _MAKERS.items():
        for i in range(per_category):
            q, expected = make(rng)
            tasks.append(Task(f"{cat}-{i}", cat, q, expected))
    return tasks


def score(task: Task, answer: str) -> bool:
    """The answer must be exactly one integer or one node letter (markdown, quotes and a final full stop are fine).
    A reply that names several numbers or letters, or explains in prose, is not accepted: the question asks for one value."""
    a = answer.strip()
    if task.category == "betweenness_top":
        m = re.fullmatch(r"[^\w-]*(?:[Nn]ode\s+)?([A-L])[^\w-]*", a)
    else:
        m = re.fullmatch(r"[^\w-]*(-?\d+)[^\w-]*", a)
    return bool(m) and m.group(1) == task.expected
