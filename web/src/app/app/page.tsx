"use client";

import { Tasks } from "../../views/Tasks";
import { useBoardData } from "../../lib/board";

export default function TasksPage() {
  const b = useBoardData();
  return <Tasks cards={b.cards} skills={b.skills} catalog={b.catalog} loaded={b.loaded} />;
}
