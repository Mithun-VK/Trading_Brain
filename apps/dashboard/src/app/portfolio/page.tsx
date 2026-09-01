import { apiGet } from "@/lib/api";
import type { PortfolioSummaryOut } from "@/lib/types";
import { ErrorBox } from "@/components/ErrorBox";

export default async function PortfolioPage() {
  const summary = await apiGet<PortfolioSummaryOut>("/portfolio/summary");

  return (
    <>
      <h1>Portfolio</h1>
      <p className="lede">Aggregated from journaled trades — not a live broker position feed.</p>

      {summary.ok ? (
        <>
          <div className="card-grid">
            <div className="card">
              <div className="stat-label">Open trades</div>
              <div className="stat-value">{summary.data.open_trade_count}</div>
            </div>
            <div className="card">
              <div className="stat-label">Open exposure value</div>
              <div className="stat-value">{summary.data.open_exposure_value.toLocaleString()}</div>
            </div>
          </div>

          <h2>Trades by status</h2>
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary.data.trades_by_status).map(([status, count]) => (
                <tr key={status}>
                  <td>{status}</td>
                  <td>{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <ErrorBox message={summary.error} />
      )}
    </>
  );
}
