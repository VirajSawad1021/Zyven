import type { NextConfig } from "next";

const API = process.env.ZYVEN_API ?? "http://localhost:8765";
const dev = process.env.NODE_ENV !== "production";

// Production: a static export served by the Zyven board server (same origin, one process).
// Development: `next dev` proxies /api to the board server.
const nextConfig: NextConfig = dev
  ? { async rewrites() { return [{ source: "/api/:path*", destination: `${API}/api/:path*` }]; } }
  : { output: "export", trailingSlash: true, images: { unoptimized: true } };

export default nextConfig;
