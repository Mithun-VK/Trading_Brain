import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { HealthOut } from "@/lib/types";
import { ErrorBox } from "@/components/ErrorBox";

const SECTIONS: Array<{ href: string; title: string; description: string }> = [
  { href: "/market", title: "Market", description: "Latest regime observation and quote lookup." },
  { href: "/watchlist", title: "Watchlist", description: "Tickers you're tracking (stored locally in your browser)." },
  { href: "/companies", title: "Companies", description: "Asset metadata and deterministic quant analysis." },
  { href: "/theses", title: "Investment Theses", description: "Look up a thesis and run a Thesis Agent review." },
  { href: "/research", title: "Research Reports", description: "Run the Research Agent and read its output." },
  { href: "/journal", title: "Trading Journal", description: "Record trades and review them individually." },
  { href: "/portfolio", title: "Portfolio", description: "Open exposure and trade counts by status." },
  { href: "/system", title: "System Health", description: "API connectivity and configuration." },
];

export default async function HomePage() {
  const health = await apiGet<HealthOut>("/health");

  return (
    <>
      <h1>TradingBrain</h1>
      <p className="lede">
        AI-assisted research and investment intelligence. This is the research and reasoning
        layer only — there is no broker execution in this system, and nothing here is
        guaranteed financial advice.
      </p>

      {health.ok ? (
        <div className="card">
          <span className={`badge badge-ok`}>API reachable</span>{" "}
          <span className="muted">env: {health.data.app_env}</span>
        </div>
      ) : (
        <ErrorBox message={health.error} />
      )}

      <h2>Sections</h2>
      <div className="card-grid">
        {SECTIONS.map((section) => (
          <Link key={section.href} href={section.href} className="card">
            <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>{section.title}</div>
            <div className="muted" style={{ fontSize: "0.85rem" }}>
              {section.description}
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
