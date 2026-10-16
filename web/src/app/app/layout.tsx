"use client";

import type { ReactNode } from "react";
import { Shell } from "../../components/Shell";
import { BoardProvider } from "../../lib/board";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <BoardProvider>
      <Shell>{children}</Shell>
    </BoardProvider>
  );
}
