/** @type {import('next').NextConfig} */
const backend = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const nextConfig = {
  onDemandEntries: {
    maxInactiveAge: 60 * 60 * 1000,
    pagesBufferLength: 12,
  },
  webpack: (config, { dev }) => {
    if (dev) {
      config.watchOptions = {
        ignored: [
          "**/node_modules/**",
          "**/.git/**",
          "**/.next/**",
          "../backend/**",
          "../android/**",
        ],
        aggregateTimeout: 300,
      };
    }
    return config;
  },
  async rewrites() {
    return [
      { source: "/health", destination: `${backend}/health` },
      { source: "/v1/:path*", destination: `${backend}/v1/:path*` },
    ];
  },
};

module.exports = nextConfig;
