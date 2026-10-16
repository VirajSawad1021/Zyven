"use client";

import { Fragment, type ReactNode } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

/* A deliberately small Markdown renderer for agent answers: headings, paragraphs, lists, rules, fenced
   code, inline code, bold, italic, and TeX maths ($…$ and $$…$$). It builds React elements, so text from
   the model is never injected as HTML; only KaTeX's own output is, and KaTeX escapes its input. */

function TeX({ src, display }: { src: string; display?: boolean }) {
  let html: string;
  try {
    html = katex.renderToString(src, { displayMode: display, throwOnError: false, output: "html", strict: "ignore" });
  } catch {
    return <code className="rounded bg-white/70 px-1 font-mono text-[12px]">{src}</code>;
  }
  return display
    ? <div className="my-2 overflow-x-auto py-1" dangerouslySetInnerHTML={{ __html: html }} />
    : <span dangerouslySetInnerHTML={{ __html: html }} />;
}

const INLINE = /(`[^`\n]+`|\$\$[^$]+\$\$|\$[^$\n]+\$|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*)/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((t, i) => {
    if (!t) return null;
    if (t.startsWith("`")) return <code key={i} className="rounded-md bg-white/80 px-1.5 py-px font-mono text-[12px] text-ink ring-1 ring-line">{t.slice(1, -1)}</code>;
    if (t.startsWith("$$")) return <TeX key={i} src={t.slice(2, -2)} />;
    if (t.startsWith("$") && t.length > 2) return <TeX key={i} src={t.slice(1, -1)} />;
    if (t.startsWith("**") || t.startsWith("__")) return <strong key={i} className="font-semibold text-ink">{inline(t.slice(2, -2))}</strong>;
    if (t.startsWith("*") && t.length > 2) return <em key={i}>{inline(t.slice(1, -1))}</em>;
    return <Fragment key={i}>{t}</Fragment>;
  });
}

type Block =
  | { k: "h"; level: number; text: string }
  | { k: "p"; text: string }
  | { k: "hr" }
  | { k: "code"; text: string }
  | { k: "math"; text: string }
  | { k: "list"; ordered: boolean; items: string[] }
  | { k: "table"; head: string[]; align: ("left" | "center" | "right")[]; rows: string[][] };

const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isRule = (line: string) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line);

const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

function parse(src: string): Block[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out: Block[] = [];
  let para: string[] = [];
  const flush = () => { if (para.length) { out.push({ k: "p", text: para.join(" ") }); para = []; } };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) { flush(); continue; }
    if (trimmed.startsWith("```")) {
      flush();
      const body: string[] = [];
      while (++i < lines.length && !lines[i].trim().startsWith("```")) body.push(lines[i]);
      out.push({ k: "code", text: body.join("\n") });
      continue;
    }
    if (trimmed.startsWith("$$")) {
      flush();
      let body = trimmed.slice(2);
      if (body.endsWith("$$") && body.length >= 2) { out.push({ k: "math", text: body.slice(0, -2) }); continue; }
      while (++i < lines.length) {
        const t = lines[i].trim();
        if (t.endsWith("$$")) { body += "\n" + t.slice(0, -2); break; }
        body += "\n" + t;
      }
      out.push({ k: "math", text: body });
      continue;
    }
    if (trimmed.startsWith("|") && i + 1 < lines.length && isRule(lines[i + 1])) {
      flush();
      const head = cells(trimmed);
      const align = cells(lines[i + 1]).map((c) => (c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : "left") as "left" | "center" | "right");
      const rows: string[][] = [];
      i++;
      while (i + 1 < lines.length && lines[i + 1].trim().startsWith("|")) rows.push(cells(lines[++i]));
      out.push({ k: "table", head, align, rows });
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (h) { flush(); out.push({ k: "h", level: h[1].length, text: h[2] }); continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) { flush(); out.push({ k: "hr" }); continue; }
    const m = LIST.exec(line);
    if (m && !line.startsWith("    ")) {
      flush();
      const ordered = /\d/.test(m[2]);
      const items: string[] = [m[3]];
      // Following lines belong to the list: new items, or indented continuations of the last item.
      while (i + 1 < lines.length) {
        const next = lines[i + 1];
        const nm = LIST.exec(next);
        if (nm && nm[1].length <= m[1].length && /\d/.test(nm[2]) === ordered) { items.push(nm[3]); i++; continue; }
        if (next.trim() && /^\s+/.test(next)) { items[items.length - 1] += "\n" + next.trim(); i++; continue; }
        if (!next.trim() && i + 2 < lines.length && (/^\s+\S/.test(lines[i + 2]) || (LIST.exec(lines[i + 2]) && /\d/.test(LIST.exec(lines[i + 2])![2]) === ordered))) { i++; continue; }
        break;
      }
      out.push({ k: "list", ordered, items });
      continue;
    }
    para.push(trimmed);
  }
  flush();
  return out;
}

function Blocks({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) => {
        switch (b.k) {
          case "h":
            return <p key={i} className={`mb-1.5 mt-3 font-semibold tracking-tight text-ink first:mt-0 ${b.level <= 2 ? "text-[15px]" : "text-[14px]"}`}>{inline(b.text)}</p>;
          case "hr":
            return <hr key={i} className="my-3 border-line" />;
          case "code":
            return <pre key={i} className="my-2 overflow-x-auto rounded-xl bg-ink px-3.5 py-2.5 font-mono text-[12px] leading-relaxed text-white/90">{b.text}</pre>;
          case "math":
            return <TeX key={i} src={b.text} display />;
          case "table":
            return (
              <div key={i} className="my-2 overflow-x-auto rounded-xl border border-line bg-white/70">
                <table className="w-full text-left text-[12.5px]">
                  <thead className="bg-panel text-[11.5px] text-muted">
                    <tr>{b.head.map((h, j) => <th key={j} className="px-3 py-2 font-semibold" style={{ textAlign: b.align[j] }}>{inline(h)}</th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {b.rows.map((r, j) => (
                      <tr key={j}>{r.map((c, k) => <td key={k} className="px-3 py-2 align-top" style={{ textAlign: b.align[k] }}>{inline(c)}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "list": {
            const L = b.ordered ? "ol" : "ul";
            return (
              <L key={i} className={`my-1.5 space-y-1 pl-5 ${b.ordered ? "list-decimal" : "list-disc"} marker:text-muted`}>
                {b.items.map((it, j) => <li key={j} className="pl-0.5"><Blocks blocks={parse(it)} /></li>)}
              </L>
            );
          }
          default:
            return <p key={i} className="my-1.5 first:mt-0 last:mb-0">{inline(b.text)}</p>;
        }
      })}
    </>
  );
}

export function Markdown({ text, className = "" }: { text: string; className?: string }) {
  return <div className={`text-[13.5px] leading-relaxed [overflow-wrap:anywhere] ${className}`}><Blocks blocks={parse(text)} /></div>;
}
