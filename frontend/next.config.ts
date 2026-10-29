// LAN users set NEXT_PUBLIC_BACKEND_ORIGIN in frontend/.env.local.
import type { NextConfig } from "next";

const isProd = process.env.NODE_ENV === "production";
const backendOrigin = process.env.NEXT_PUBLIC_BACKEND_ORIGIN || (isProd ? "" : "http://localhost:8000");

// In production: drop unsafe-eval from script-src and remove localhost/127.0.0.1 from connect-src
const cspValue = isProd
  ? [
      "default-src 'self' https: data: blob:",
      "script-src 'self' 'unsafe-inline' blob:",
      "style-src 'self' 'unsafe-inline' https:",
      "img-src 'self' data: blob: https:",
      "worker-src 'self' blob:",
      `connect-src 'self' ${backendOrigin && !backendOrigin.includes('localhost') && !backendOrigin.includes('127.0.0.1') ? backendOrigin + ' ' : ''}https: wss: data: blob:`,
    ].join("; ") + ";"
  : `default-src 'self' 'unsafe-inline' 'unsafe-eval' http: https: ws: wss: data: blob:; connect-src 'self' http://localhost:8000 http://127.0.0.1:8000 ${backendOrigin} ws: wss: data: blob:;`;

const nextConfig: NextConfig = {
  output: 'standalone',
  serverExternalPackages: ['ws'],
  transpilePackages: ['react-map-gl', 'mapbox-gl', 'maplibre-gl'],
  typescript: {
    ignoreBuildErrors: false,
  },
  async rewrites() {
    const backendUrl = process.env.NEXA_BACKEND_URL || process.env.BACKEND_URL || 'http://127.0.0.1:8000';
    return [
      {
        source: '/api/nexa/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          {
            key: 'Content-Security-Policy',
            value: cspValue,
          },
          { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          ...(process.env.ALLOW_IFRAME_EMBED === '1'
            ? []
            : [{ key: 'X-Frame-Options', value: 'SAMEORIGIN' }]),
          { key: 'X-XSS-Protection', value: '1; mode=block' },
        ],
      },
    ];
  },
};

export default nextConfig;
