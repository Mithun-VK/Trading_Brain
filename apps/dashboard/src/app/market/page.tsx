import { apiGet } from "@/lib/api";
import type { MarketRegimeOut } from "@/lib/types";
import { ErrorBox } from "@/components/ErrorBox";
import { QuoteLookup } from "./QuoteLookup";

export default async function MarketPage() {
  const regime = await apiGet<MarketRegimeOut>("/market/regime");

  return (
    <>
      <h1>Market</h1>
      <p className="lede">
        Regime classifications are descriptive, not predictive — they describe what a
        rule-based detector observed in the data, never a forecast.
      </p>

      <h2>Latest regime observation</h2>
      {regime.ok ? (
        <div className="card-grid">
          <div className="card">
            <div className="stat-label">Trend</div>
            <div className="stat-value">{regime.data.trend_regime}</div>
          </div>
          <div className="card">
            <div className="stat-label">Volatility</div>
            <div className="stat-value">{regime.data.volatility_regime}</div>
          </div>
          <div className="card">
            <div className="stat-label">Risk</div>
            <div className="stat-value">{regime.data.risk_regime}</div>
          </div>
        </div>
      ) : (
        <ErrorBox message={regime.error} />
      )}
      {regime.ok && (
        <p className="muted" style={{ fontSize: "0.8rem" }}>
          observed at {new Date(regime.data.observed_at).toLocaleString()} · scope {regime.data.scope}
        </p>
      )}

      <h2>Quote lookup</h2>
      <QuoteLookup />
    </>
  );
}
