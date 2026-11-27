const backend = (process.env.EFA_BACKEND_ORIGIN || "http://127.0.0.1:8765").replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const config = {
  poweredByHeader: false,
  experimental: {
    middlewareClientMaxBodySize: "101mb",
    proxyTimeout: 600000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default config;
