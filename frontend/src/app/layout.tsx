import type { Metadata, Viewport } from "next";
import { Archivo, IBM_Plex_Mono } from 'next/font/google';
import GlobalBackdrop from '@/components/art/GlobalBackdrop';
import ErrorBoundary from '@/components/ErrorBoundary';
import { AuthProvider } from '@/store/useAuthStore';
import TacticalNavRail from '@/components/TacticalNavRail';
import CopilotQuickDock from '@/components/CopilotQuickDock';
import BackendColdStartBanner from '@/components/BackendColdStartBanner';
import "./globals.css";

const archivo = Archivo({
  variable: '--font-archivo',
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700'],
  display: 'swap',
});

const ibmPlexMono = IBM_Plex_Mono({
  variable: '--font-plex-mono',
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  display: 'swap',
});

const SITE_URL = "https://nexafreight.dev";
const SITE_NAME = "NexaFreight Control Tower";
const SITE_TITLE = "NexaFreight Control Tower | Multimodal Freight Intelligence Platform";
const SITE_DESCRIPTION = "Real-time multimodal freight tracking, predictive ML risk assessment, vessel telemetry, and situational control tower.";

export const viewport: Viewport = {
  themeColor: "#2547C8",
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  colorScheme: "light",
};

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: SITE_TITLE,
    template: "%s | NexaFreight Control Tower",
  },
  description: SITE_DESCRIPTION,
  keywords: [
    // Freight & Logistics
    "multimodal freight", "freight tracking", "logistics control tower", "supply chain visibility",
    "vessel tracking", "ocean freight", "air cargo tracking", "container tracking",
    "freight intelligence", "predictive logistics", "ML freight delay", "demurrage tracker",
    "SLA risk management", "freight optimization", "port congestion", "route disruption",
    "cargo telemetry", "shipment visibility", "freight dashboard", "logistics platform",
    "ESG carbon accounting", "shipping emissions", "CO2 freight",
    // Brand
    "nexafreight", "nexafreight control tower", "nexafreight platform",
  ],
  authors: [{ name: "NexaFreight", url: SITE_URL }],
  creator: "NexaFreight",
  publisher: "NexaFreight",
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/favicon-32x32.png", type: "image/png", sizes: "32x32" },
      { url: "/favicon-16x16.png", type: "image/png", sizes: "16x16" },
      { url: "/android-chrome-192x192.png", type: "image/png", sizes: "192x192" },
      { url: "/android-chrome-512x512.png", type: "image/png", sizes: "512x512" },
    ],
    apple: [
      { url: "/apple-touch-icon.png", sizes: "180x180" },
    ],
    shortcut: "/favicon.ico",
    other: [
      {
        rel: "apple-touch-icon-precomposed",
        url: "/apple-touch-icon.png",
      },
    ],
  },
  manifest: "/site.webmanifest",
  alternates: {
    canonical: SITE_URL,
  },
  openGraph: {
    title: "NexaFreight Control Tower | Multimodal Freight Intelligence Platform",
    description: SITE_DESCRIPTION,
    type: "website",
    siteName: SITE_NAME,
    locale: "en_US",
    url: SITE_URL,
    images: [
      {
        url: `${SITE_URL}/og-image.png`,
        width: 1200,
        height: 630,
        alt: "NexaFreight Control Tower",
        type: "image/png",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "NexaFreight Control Tower | Multimodal Freight Intelligence",
    description: SITE_DESCRIPTION,
    creator: "@nexafreight",
    site: "@nexafreight",
    images: [`${SITE_URL}/og-image.png`],
  },
  category: "logistics",
  classification: "Supply Chain & Logistics Intelligence",
  other: {
    "apple-mobile-web-app-capable": "yes",
    "apple-mobile-web-app-status-bar-style": "black-translucent",
    "apple-mobile-web-app-title": "NexaFreight",
    "mobile-web-app-capable": "yes",
    "msapplication-TileColor": "#06060C",
    "msapplication-config": "none",
  },
};

// JSON-LD Structured Data
const jsonLd = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "NexaFreight Control Tower",
  alternateName: ["NexaFreight", "NexaFreight Platform"],
  url: SITE_URL,
  description: SITE_DESCRIPTION,
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  browserRequirements: "Requires a modern web browser",
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "USD",
    availability: "https://schema.org/InStock",
  },
  featureList: [
    "Nmap port scanning from the browser — no install required",
    "DNS record lookup (A, AAAA, MX, NS, TXT, CNAME)",
    "WHOIS domain registration lookup",
    "SSL/TLS certificate transparency search",
    "BGP routing & ASN lookup",
    "IP geolocation & threat intelligence",
    "Real-time flight tracking (10,000+ aircraft via ADS-B)",
    "Satellite tracking (2,000+ objects including ISS)",
    "Worldwide CCTV camera monitoring (1,400+ feeds)",
    "Earthquake monitoring (USGS live feed)",
    "Wildfire detection (NASA FIRMS satellite data)",
    "Nuclear facility mapping (worldwide)",
    "Severe weather alerts & tracking",
    "Cyber threat & CVE intelligence",
    "Space weather & solar storm monitoring",
    "GPS jamming detection",
    "Defense & commodity market tracking",
    "SIGINT news aggregation feed",
    "Interactive 3D globe with day/night cycle",
    "Region intelligence dossier reports",
  ],
  screenshot: `${SITE_URL}/og-image.png`,
  author: {
    "@type": "Organization",
    name: "NexaFreight Project",
    url: SITE_URL,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning className={`${archivo.variable} ${ibmPlexMono.variable}`}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png" />
        <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="canonical" href={SITE_URL} />
        
        {/* JSON-LD Structured Data */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />

      </head>
      <body className="antialiased">
        <GlobalBackdrop />
        <div style={{ position: 'relative', zIndex: 1 }}>
        <ErrorBoundary name="NexaFreight Core">
          <AuthProvider>
            <TacticalNavRail />
            {children}
            <CopilotQuickDock />
            <BackendColdStartBanner />
          </AuthProvider>
        </ErrorBoundary>
      </div>
      </body>
    </html>
  );
}
