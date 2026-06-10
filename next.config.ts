import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: false,
  serverExternalPackages: ["pg", "yaml"]
};

export default nextConfig;
