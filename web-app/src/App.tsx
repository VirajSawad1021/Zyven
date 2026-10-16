import { useEffect, useState } from "react";
import { Shell, type ViewId } from "./components/Shell";
import { useBoard } from "./lib/useBoard";
import { Control } from "./views/Control";
import { Explorer } from "./views/Explorer";
import { Insights } from "./views/Insights";
import { Catalog, Skills } from "./views/Skills";
import { Tasks } from "./views/Tasks";

const VIEWS: ViewId[] = ["tasks", "control", "skills", "insights", "explore", "catalog"];
const fromHash = (): ViewId => {
  const v = location.hash.replace("#/", "") as ViewId;
  return VIEWS.includes(v) ? v : "tasks";
};

export default function App() {
  const [view, setView] = useState<ViewId>(fromHash);
  const board = useBoard();

  useEffect(() => {
    const on = () => { setView(fromHash()); window.scrollTo({ top: 0 }); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const approvals = board.cards.filter((c) => c.status === "NEEDS_APPROVAL").length;

  return (
    <Shell view={view} conn={board.conn} wide={view === "explore"} counts={{ tasks: approvals, skills: board.skills.length }}>
      {view === "tasks" && <Tasks cards={board.cards} skills={board.skills} loaded={board.loaded} />}
      {view === "control" && <Control />}
      {view === "skills" && <Skills skills={board.skills} onGoTasks={() => { location.hash = "#/tasks"; }} />}
      {view === "insights" && <Insights stats={board.stats} />}
      {view === "explore" && <Explorer />}
      {view === "catalog" && <Catalog repos={board.catalog} />}
    </Shell>
  );
}
