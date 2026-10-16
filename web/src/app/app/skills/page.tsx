"use client";

import { useRouter } from "next/navigation";
import { Skills } from "../../../views/Skills";
import { useBoardData } from "../../../lib/board";

export default function SkillsPage() {
  const { skills } = useBoardData();
  const router = useRouter();
  return <Skills skills={skills} onGoTasks={() => router.push("/app/")} />;
}
