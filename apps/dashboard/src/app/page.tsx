import Link from "next/link";
import { apiGetAll } from "@/lib/api";
import type {
  PortfolioOut,
  ResearchQueueOut,
  SignalOut,
} from "@/lib/types";
import { ErrorBox } from "@/components/Section";
import { Money, Pct } from "@/components/Value";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [portfolio, signals, queue] = await apiGetAll<
    [PortfolioOut, SignalOut[], ResearchQueueOut[]]
  >("/portfolio", "/signals/latest?limit=5", "/research/queue?status=pending&limit=5");

  return (
    <>
      <h1>Overview</h1>
      <p className="lede">
        A research and reasoning system. It forms views, records why, and checks itself against what
        happened. It does not place orders — no broker is connected and no execution path exists.
      </p>

      <h2>Portfolio</h2>
      {portfolio.ok ? (
        <div className="card-grid">
          <div className="card">
            <div className="stat-label">Total value</div>
            <div className="stat-value">
              <Money value={portfolio.data.total_value} currency={portfolio.data.base_currency} />
            </div>
          </div>
          <div className="card">
            <div className="stat-label">Total return</div>
            <div className="stat-value">
              <Pct value={portfolio.data.total_return} signed />
            </div>
          </div>
          <div className="card">
            <div className="stat-label">Positions</div>
            <div className="stat-value">{portfolio.data.position_count}</div>
            {portfolio.data.unpriced_positions > 0 ? (
              <div className="stat-caveat">
                {portfolio.data.unpriced_positions} unpriced and excluded from value
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <ErrorBox message={portfolio.error} what="the portfolio" />
      )}

      <h2>Latest signals</h2>
      {signals.ok ? (
        signals.data.length === 0 ? (
          <div className="empty-state">No signals yet.</div>
        ) : (
          <ul className="plain">
            {signals.data.map((s) => (
              <li key={s.id}>
                <span className={`badge cat-${s.category.toLowerCase()}`}>{s.category}</span>{" "}
                <strong>{s.ticker}</strong>{" "}
                <span className="muted small">
                  {s.evidence.length} piece{s.evidence.length === 1 ? "" : "s"} of evidence
                </span>
              </li>
            ))}
          </ul>
        )
      ) : (
        <ErrorBox message={signals.error} what="signals" />
      )}

      <h2>Research queue</h2>
      {queue.ok ? (
        queue.data.length === 0 ? (
          <div className="empty-state">Nothing queued for research.</div>
        ) : (
          <ul className="plain">
            {queue.data.map((q) => (
              <li key={q.id}>
                <strong>{q.ticker}</strong> <span className="badge">{q.change_type}</span>{" "}
                <span className="muted small">priority {q.score.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        )
      ) : (
        <ErrorBox message={queue.error} what="the research queue" />
      )}

      <p style={{ marginTop: "1.75rem" }}>
        <Link className="link" href="/system">
          Check system health →
        </Link>
      </p>
    </>
  );
}
