import type { NextConfig } from "next";
const config: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Cache-Control", value: "no-store" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Content-Security-Policy",
            value:
              "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
          },
        ],
      },
    ];
  },
};
export default config;
