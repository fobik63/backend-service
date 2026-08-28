import type { NextConfig } from "next";
import os from "os";
import path from "path";

/** Non-loopback IPv4 hosts for Next.js `allowedDevOrigins` (phone / LAN HMR). */
function lanDevOrigins(): string[] {
  const hosts: string[] = [];
  for (const addrs of Object.values(os.networkInterfaces())) {
    for (const addr of addrs ?? []) {
      // Node historically used numeric family (4/6); current typings are strings.
      const family = addr.family as string | number;
      const isV4 = family === "IPv4" || family === 4;
      if (!isV4 || addr.internal) continue;
      hosts.push(addr.address);
    }
  }
  return hosts;
}

const nextConfig: NextConfig = {
  output: "standalone",
  turbopack: {
    root: path.join(__dirname),
  },
  allowedDevOrigins: ["127.0.0.1", "localhost", ...lanDevOrigins()],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://telegram.org",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob: https:",
              "font-src 'self' data:",
              "connect-src 'self' http: https: ws: wss:",
              "frame-src https://oauth.telegram.org https://telegram.org",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
              "object-src 'none'",
            ].join("; "),
          },
        ],
      },
    ];
  },
  serverExternalPackages: [
    "puppeteer",
    "puppeteer-extra",
    "puppeteer-extra-plugin-stealth",
  ],
};

export default nextConfig;
