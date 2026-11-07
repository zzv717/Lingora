/** @type {import('next').NextConfig} */
const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // The browser only ever talks to this origin; the Next server proxies API
    // calls to the FastAPI backend (works in previews, avoids CORS entirely).
    return [
      { source: "/backend/:path*", destination: `${BACKEND_URL}/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/pdf.worker.min.js",
        headers: [{ key: "Content-Type", value: "application/javascript" }],
      },
    ];
  },
};

export default nextConfig;
