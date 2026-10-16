import type { CardEvent } from "./types";

export type Tone = "neutral" | "good" | "warn" | "bad" | "info" | "dark";

export const EXAMPLES = [
  { label: "BS date today", text: "Today is 2026-10-12 (AD). What is today's date in Bikram Sambat, and which operator is 9801234567?" },
  { label: "BS → AD", text: "Convert BS 2082-06-15 to the Gregorian date." },
  { label: "IBAN check", text: "Is the IBAN GB82 WEST 1234 5698 7654 32 valid? Also format it with spaces." },
  { label: "Global phone", text: "Parse +44 20 7930 4832: is it valid, what type is it, and which region?" },
  { label: "Symbolic math", text: "Using a symbolic math engine, factor x**15 - 1 over the integers and compute the exact definite integral of 1/(x**4+1) from 0 to infinity." },
];

export const STATUS: Record<string, { label: string; tone: Tone }> = {
  QUEUED: { label: "Queued", tone: "neutral" },
  RUNNING: { label: "Running", tone: "info" },
  GAP_CHECK: { label: "Gap check", tone: "info" },
  SKILL_REUSED: { label: "Reusing skill", tone: "good" },
  SEARCHING: { label: "Searching", tone: "info" },
  NO_MATCH: { label: "No match", tone: "warn" },
  NEEDS_APPROVAL: { label: "Needs approval", tone: "warn" },
  REJECTED: { label: "Rejected", tone: "bad" },
  COMPILING: { label: "Compiling", tone: "info" },
  COMPILE_FAILED: { label: "Compile failed", tone: "bad" },
  SKILL_LEARNED: { label: "Skill learned", tone: "good" },
  RESUMED: { label: "Resumed", tone: "info" },
  DONE: { label: "Done", tone: "good" },
  FAILED: { label: "Failed", tone: "bad" },
};

export const LIVE_STATES = new Set(["QUEUED", "RUNNING", "GAP_CHECK", "SEARCHING", "COMPILING", "RESUMED", "SKILL_REUSED"]);

const EV_LABEL: Record<string, string> = {
  RUNNING: "Agent started", GAP_CHECK: "Gap check", SKILL_REUSED: "Skill reused",
  SEARCHING: "Searching catalog", NO_MATCH: "No catalog match", NEEDS_APPROVAL: "Approval requested",
  REJECTED: "Rejected", COMPILING: "Compiling", COMPILE_FAILED: "Compile failed",
  SKILL_LEARNED: "Skill learned", RESUMED: "Resumed with tools", DONE: "Done", FAILED: "Failed",
  "approval.decision": "Decision",
};

const COMPILE_LABEL: Record<string, string> = {
  "architect.start": "Architect", "architect.done": "Architect",
  "compiler.start": "Compiler", "compiler.done": "Compiler",
  "tester.start": "Tester", "tester.done": "Tester", "tester.error": "Tester",
  "verify.start": "Verify", "verify.partial": "Re-verify",
  "gate.policy": "Gate · policy", "gate.import": "Gate · imports",
  "gate.upstream_tests": "Gate · upstream tests", "gate.input_robustness": "Gate · input robustness",
  "gate.mcp_smoke": "Gate · MCP smoke", "gate.differential": "Gate · differential",
  "repair.start": "Repair", "repair.done": "Repair", "repair.error": "Repair",
  done: "Compile result",
};

export function eventLabel(kind: string): string {
  return kind.startsWith("compile.") ? COMPILE_LABEL[kind.replace("compile.", "")] ?? kind : EV_LABEL[kind] ?? kind;
}

export function eventTone(e: CardEvent): "ok" | "bad" | "warn" | "info" | "ink" {
  const { kind, data } = e;
  if (["DONE", "SKILL_LEARNED", "SKILL_REUSED"].includes(kind)) return "ok";
  if (["FAILED", "COMPILE_FAILED", "REJECTED", "NO_MATCH"].includes(kind)) return "bad";
  if (kind === "NEEDS_APPROVAL") return "warn";
  if (kind.startsWith("compile.")) {
    if (data.passed === false) return "bad";
    if (data.passed === true) return "ok";
    if (kind === "compile.done") return data.verified === false ? "bad" : "ok";
    return "info";
  }
  if (kind === "approval.decision") return String(data.detail ?? "").startsWith("approved") ? "ok" : "bad";
  if (kind === "RUNNING") return "ink";
  return "info";
}

export function eventDetail(e: CardEvent): string {
  const raw = String(e.data.detail ?? e.data.reason ?? "");
  return e.kind.startsWith("compile.gate.") ? raw.replace(/^(PASS|FAIL) /, "") : raw;
}

export function relTime(ts: number): string {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 8) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
