import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Signal Radar",
  description: "Manual signal ingestion, analyzer jobs, memory update audit."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <header className="topbar">
          <Link href="/" className="brand" aria-label="Signal Radar home">
            <span className="brand-mark">SR</span>
            <span>
              <strong>Signal Radar</strong>
              <small>Next.js 16 TypeScript runtime</small>
            </span>
          </Link>
          <nav className="topnav" aria-label="Primary">
            <Link href="/">Ingest</Link>
            <Link href="/api/healthz">Health</Link>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
