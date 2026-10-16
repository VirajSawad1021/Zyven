import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Card, CatalogRepo, Skill, Stats } from "./types";

export type Conn = "connecting" | "live" | "reconnecting";

/** All board data: cards stream in over SSE; skills, catalog and stats are refetched on change. */
export function useBoard() {
  const [cards, setCards] = useState<Map<string, Card>>(new Map());
  const [skills, setSkills] = useState<Skill[]>([]);
  const [catalog, setCatalog] = useState<CatalogRepo[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [conn, setConn] = useState<Conn>("connecting");
  const [, tick] = useState(0);

  const refreshSkills = useCallback(() => api<Skill[]>("/api/skills").then(setSkills).catch(() => {}), []);
  const refreshStats = useCallback(() => api<Stats>("/api/stats").then(setStats).catch(() => {}), []);
  const refreshStatsRef = useRef(refreshStats);
  const refreshSkillsRef = useRef(refreshSkills);
  refreshStatsRef.current = refreshStats;
  refreshSkillsRef.current = refreshSkills;

  useEffect(() => {
    api<Card[]>("/api/cards")
      .then((list) => setCards(new Map(list.map((c) => [c.id, c]))))
      .catch(() => {})
      .finally(() => setLoaded(true));
    api<CatalogRepo[]>("/api/catalog").then(setCatalog).catch(() => {});
    refreshSkills();
    refreshStats();

    const es = new EventSource("/api/stream");
    es.onopen = () => setConn("live");
    es.onerror = () => setConn("reconnecting");
    es.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.type === "card") {
        setCards((prev) => new Map(prev).set(msg.card.id, msg.card));
        refreshSkillsRef.current();
        refreshStatsRef.current();
      } else if (msg.type === "event") {
        setCards((prev) => {
          const c = prev.get(msg.card);
          if (!c) return prev;
          const next = new Map(prev);
          next.set(c.id, {
            ...c,
            events: [...(c.events ?? []), { kind: msg.kind, data: msg.data }],
            status: msg.status ?? c.status,
            updated: Date.now() / 1000,
          });
          return next;
        });
        if (msg.kind === "SKILL_LEARNED") refreshSkillsRef.current();
        if (msg.status === "DONE" || msg.status === "FAILED") refreshStatsRef.current();
      }
    };
    const t = setInterval(() => tick((n) => n + 1), 30_000); // keep "2m ago" labels fresh
    return () => {
      es.close();
      clearInterval(t);
    };
  }, [refreshSkills, refreshStats]);

  const list = [...cards.values()].sort((a, b) => b.created - a.created);
  return { cards: list, skills, catalog, stats, loaded, conn, refreshStats };
}
