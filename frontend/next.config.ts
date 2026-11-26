import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Keep E2E production builds separate from a running dev server's cache.
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;

