/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy API, static files, and WebSocket requests to FastAPI backend
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8002";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/static/:path*",
        destination: `${backendUrl}/static/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `${backendUrl}/ws/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
