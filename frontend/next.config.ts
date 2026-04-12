import type { NextConfig } from "next";

const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  rewrites: async () => [
    {
      source: "/api/:path*",
      destination: `${backendUrl}/api/:path*`,
    },
    {
      source: "/health",
      destination: `${backendUrl}/health`,
    },
    {
      source: "/ws/:path*",
      destination: `${backendUrl}/ws/:path*`,
    },
  ],
};

export default nextConfig;
