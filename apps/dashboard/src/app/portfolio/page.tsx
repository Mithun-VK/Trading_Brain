import { apiGetAll } from "@/lib/api";
import type { ExposureOut, PortfolioOut, PortfolioPerformanceOut, PositionOut } from "@/lib/types";
import { EmptyState, ErrorBox, Loaded } from "@/components/Section";
import { Money, Num, Pct, Stat, Unknown } from "@/components/Value";

export const dynamic = "force-dynamic";

export default async function PortfolioPage() {
  const [portfolio, positions, performance, exposure] = await apiGetAll<
    [PortfolioOut, PositionOut[], PortfolioPerformanceOut, ExposureOut]
  >("/portfolio", "/portfolio/positions", "/portfolio/performance", "/portfolio/exposure");

  const currency = portfolio.ok ? portfolio.data.base_currency : undefined;

  return (
    <>
      <h1>Portfolio</h1>
      <p className="lede">
        A paper portfolio maintained from journaled activity. It is not connected to a broker and
        does not reflect any real holding.
      </p>

      <Loaded result={portfolio} what="the portfolio">
        {(p) => (
          <>
            {/* An unpriced position is excluded from market value rather than
                valued at cost, so total value would silently understate the
                portfolio if this went unsaid (Rule 4). */}
            {p.unpriced_positions > 0 ? (
              <p className="notice">
                {p.unpriced_positions} position{p.unpriced_positions === 1 ? "" : "s"} had no
                current price and {p.unpriced_positions === 1 ? "is" : "are"} excluded from market
                value. Totals below are therefore incomplete, not merely stale.
              </p>
            ) : null}

            <div className="card-grid">
              <Stat label="Total value">
                <Money value={p.total_value} currency={currency} />
              </Stat>
              <Stat label="Cash">
                <Money value={p.cash} currency={currency} />
              </Stat>
              <Stat label="Unrealized P&L">
                <Money value={p.unrealized_pnl} currency={currency} signed />
              </Stat>
              <Stat label="Realized P&L">
                <Money value={p.realized_pnl} currency={currency} signed />
              </Stat>
              <Stat label="Total return">
                <Pct value={p.total_return} signed />
              </Stat>
              <Stat label="Exposure">
                <Pct value={p.exposure} />
              </Stat>
            </div>
          </>
        )}
      </Loaded>

      <h2>Performance</h2>
      <Loaded
        result={performance}
        what="performance"
        isEmpty={(d) => d.snapshots === 0}
        empty="No portfolio snapshots recorded yet. Performance needs a history to measure against."
      >
        {(d) => (
          <>
            {d.caveat ? <p className="notice">{d.caveat}</p> : null}
            {!d.fully_priced ? (
              <p className="notice">
                Some positions were unpriced when these figures were computed.
              </p>
            ) : null}
            <div className="card-grid">
              <Stat label="Daily return" caveat={d.snapshots < 2 ? `${d.snapshots} snapshot` : null}>
                {/* One snapshot is not a return. The API sends null here and
                    the UI must not turn that into a flat day. */}
                <Pct
                  value={d.daily_return}
                  signed
                  kind="insufficient"
                  note="At least two snapshots are needed to compute a daily return"
                />
              </Stat>
              <Stat label="CAGR">
                <Pct value={d.cagr} signed />
              </Stat>
              <Stat label="Sharpe">
                <Num value={d.sharpe} />
              </Stat>
              <Stat label="Volatility">
                <Pct value={d.volatility} />
              </Stat>
              <Stat label="Max drawdown">
                <Pct value={d.max_drawdown} />
              </Stat>
              <Stat label="Snapshots">
                <Num value={d.snapshots} digits={0} />
              </Stat>
            </div>
          </>
        )}
      </Loaded>

      <h2>Positions</h2>
      <Loaded
        result={positions}
        what="positions"
        isEmpty={(d) => d.length === 0}
        empty="No open positions."
      >
        {(data) => (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Qty</th>
                  <th>Avg cost</th>
                  <th>Price</th>
                  <th>Market value</th>
                  <th>Unrealized</th>
                  <th>Weight</th>
                </tr>
              </thead>
              <tbody>
                {data.map((pos) => (
                  <tr key={pos.ticker} className={pos.unpriced ? "row-unpriced" : undefined}>
                    <td>
                      <strong>{pos.ticker}</strong>
                    </td>
                    <td>
                      <Num value={pos.quantity} digits={0} />
                    </td>
                    <td>
                      <Num value={pos.average_cost} />
                    </td>
                    <td>
                      <Num
                        value={pos.current_price}
                        kind="unpriced"
                        note="No current price was available from any configured provider"
                      />
                    </td>
                    <td>
                      {pos.unpriced ? (
                        <Unknown kind="unpriced" note="Excluded from portfolio market value" />
                      ) : (
                        <Money value={pos.market_value} />
                      )}
                    </td>
                    <td>
                      {pos.unpriced ? (
                        <Unknown kind="unpriced" />
                      ) : (
                        <Money value={pos.unrealized_pnl} signed />
                      )}
                    </td>
                    <td>
                      {pos.unpriced ? <Unknown kind="unpriced" /> : <Pct value={pos.allocation} />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loaded>

      <h2>Exposure</h2>
      {!exposure.ok ? (
        <ErrorBox message={exposure.error} what="exposure" />
      ) : exposure.data.by_sector.length === 0 ? (
        <EmptyState>
          No sector exposure to report. Sector data comes from company fundamentals, which may not
          have been ingested.
        </EmptyState>
      ) : (
        <div className="card">
          {exposure.data.by_sector.map((b) => (
            <div key={b.label} className="score-bar">
              <span className="score-bar-label">{b.label}</span>
              <span className="score-bar-track">
                <span
                  className="score-bar-fill"
                  style={{ width: `${Math.max(0, Math.min(1, b.weight)) * 100}%` }}
                />
              </span>
              <span className="score-bar-value">
                <Pct value={b.weight} digits={1} />
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
