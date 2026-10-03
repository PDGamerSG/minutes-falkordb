import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output for the Docker image (apps/web/Dockerfile).
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
