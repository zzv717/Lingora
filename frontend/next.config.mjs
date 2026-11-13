/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  webpack(config) {
    // pdf.js is loaded only in the browser; its optional Node canvas is unnecessary.
    config.resolve.alias.canvas = false;
    return config;
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
