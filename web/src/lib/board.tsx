"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useBoard } from "./useBoard";

type Board = ReturnType<typeof useBoard>;
const Ctx = createContext<Board | null>(null);

/** One SSE connection for the whole app: every view reads the same live board. */
export function BoardProvider({ children }: { children: ReactNode }) {
  return <Ctx.Provider value={useBoard()}>{children}</Ctx.Provider>;
}

export function useBoardData(): Board {
  const b = useContext(Ctx);
  if (!b) throw new Error("useBoardData outside BoardProvider");
  return b;
}
