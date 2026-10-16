import Link from "next/link";

export default function Home() {
  return (
    <main className="grid min-h-screen place-items-center">
      <Link href="/app/" className="rounded-full bg-ink px-5 py-2.5 text-[14px] font-semibold text-white">Open the board</Link>
    </main>
  );
}
