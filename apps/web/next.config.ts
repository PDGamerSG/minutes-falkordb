import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output for the Docker image (apps/web/Dockerfile).
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // Explicit private-network hostnames for a connected-device preview.
  allowedDevOrigins: process.env.MINUTES_DEV_ORIGINS?.split(",").filter(Boolean),
};

export default nextConfig;
