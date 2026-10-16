export interface CardEvent {
  kind: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
  seq?: number;
  ts?: number;
}

export interface Card {
  id: string;
  task: string;
  status: string;
  created: number;
  updated: number;
  answer: string | null;
  learned: string[];
  reused: string[];
  events: CardEvent[];
}

export interface Skill {
  name: string;
  title?: string;
  summary?: string;
  source: string;
  verified_for: string[];
  tools: string[];
  health?: { ok: number; calls: number };
}

export interface CatalogRepo {
  repo: string;
  url: string;
  commit: string;
  license: string;
  note: string;
}

export interface StatsCard {
  id: string;
  task: string;
  status: string;
  created: number;
  duration: number | null;
  learned: string[];
  reused: string[];
  compiled: boolean;
  compiles: number;
}

export interface Stats {
  totals: { tasks: number; done: number; skills: number; reuses: number };
  averages: { compile_s: number | null; reuse_s: number | null };
  cards: StatsCard[];
  gates: Record<string, { pass: number; fail: number }>;
}

export interface ExploreRepo {
  repo: string;
  note: string;
  license: string;
  cloned: boolean;
  job: { state: "idle" | "running" | "done" | "error"; error?: string };
  analyzed: boolean;
  symbols: number | null;
  mcp_able: number | null;
}

export interface FunnelStage { stage: string; count: number; note: string }
export interface GraphNode { id: string; loc: number; symbols: number; mcp_able: number; capability: string | null }
export interface GraphEdge { source: string; target: string; weight: number }
export interface Candidate {
  id: string;
  params: string[];
  returns: string | null;
  tested: boolean;
  capability: string | null;
  doc: string;
}
export interface ExploreData {
  repo: string;
  commit: string | null;
  license: string | null;
  totals: { modules: number; test_files: number; tests: number; classes: number; loc: number };
  funnel: FunnelStage[];
  capabilities: { name: string; title: string; entry_points: number }[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[]; total_modules: number; shown: number };
  top_candidates: Candidate[];
  warnings: string[];
  analyzed_in_s: number;
}
