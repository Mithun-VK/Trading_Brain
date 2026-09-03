import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "TradingBrain",
  description: "AI-assisted trading and investment intelligence — research foundation, not an autonomous trading bot.",
};

const NAV_LINKS: Array<{ href: string; label: string }> = [
  { href: "/", label: "Overview" },
  { href: "/signals", label: "Signals" },
  { href: "/intelligence", label: "Queue" },
  { href: "/market", label: "Market" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/companies", label: "Companies" },
  { href: "/theses", label: "Theses" },
  { href: "/research", label: "Research" },
  { href: "/journal", label: "Journal" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/paper", label: "Paper" },
  { href: "/backtests", label: "Backtests" },
  { href: "/learning", label: "Learning" },
  { href: "/ai", label: "AI Ops" },
  { href: "/system", label: "System" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <div className="site-header-inner">
            <span className="brand">TradingBrain</span>
            <nav className="main-nav">
              {NAV_LINKS.map((link) => (
                <Link key={link.href} href={link.href}>
                  {link.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="page-container">{children}</main>
        <footer className="site-footer">
          Research and analysis only. Not financial advice. No broker execution exists in this
          system.
        </footer>
      </body>
    </html>
  );
}
