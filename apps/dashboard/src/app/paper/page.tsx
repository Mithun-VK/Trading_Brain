import { apiGetAll } from "@/lib/api";
import type { PaperTradeOut, PaperTradePerformanceOut } from "@/lib/types";
import { Loaded } from "@/components/Section";
import { Money, Num, SampledMetric, Unknown } from "@/components/Value";

export const dynamic = "force-dynamic";

export default async function PaperTradingPage() {
  const [perf, trades] = await apiGetAll<[PaperTradePerformanceOut, PaperTradeOut[]]>(
    "/paper-trades/performance",
    "/paper-trades?limit=100",
  );

  return (
    <>
      <h1>Paper Trading</h1>
      <p className="lede">
        Simulated positions only. No broker is connected to this system and no order has ever left
        it. Positions are opened and closed by explicit confirmation, never as a side effect.
      </p>

      <h2>Performance</h2>
      <Loaded
        result={perf}
        what="paper trading performance"
        isEmpty={(d) => d.trade_count === 0}
        empty="No paper trades recorded yet. Performance statistics need closed trades before they mean anything."
      >
        {(d) => (
          <>
            {/* scored_trades, not trade_count, is the denominator that matters:
                an open position has no outcome to be right or wrong about. */}
            {d.scored_trades < d.trade_count ? (
              <p className="notice">
                {d.trade_count} trades recorded, {d.scored_trades} closed and scored. The figures
                below describe the closed ones only.
              </p>
            ) : null}
            {d.caveat ? <p className="notice">{d.caveat}</p> : null}

            <div className="card-grid">
              <SampledMetric
                label="Win rate"
                value={d.scored_trades > 0 ? d.win_rate : null}
                sampleSize={d.scored_trades}
                isSignificant={d.is_significant}
              />
              <SampledMetric
                label="Expectancy (R)"
                value={d.scored_trades > 0 ? d.expectancy_r : null}
                sampleSize={d.scored_trades}
                isSignificant={d.is_significant}
                render={(v) => <Num value={v} digits={2} suffix="R" />}
              />
              <SampledMetric
                label="Profit factor"
                value={d.scored_trades > 0 ? d.profit_factor : null}
                sampleSize={d.scored_trades}
                isSignificant={d.is_significant}
                render={(v) => <Num value={v} digits={2} />}
              />
              <SampledMetric
                label="Max drawdown"
                value={d.scored_trades > 0 ? d.max_drawdown : null}
                sampleSize={d.scored_trades}
                isSignificant={d.is_significant}
              />
            </div>
          </>
        )}
      </Loaded>

      <h2>Positions</h2>
      <Loaded
        result={trades}
        what="paper trades"
        isEmpty={(d) => d.length === 0}
        empty="No paper positions have been opened."
      >
        {(data) => (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Dir</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Realized P&amp;L</th>
                  <th>R</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <strong>{t.ticker}</strong>
                    </td>
                    <td>{t.direction}</td>
                    <td>
                      <Num value={t.quantity} digits={0} />
                    </td>
                    <td>
                      <Num value={t.entry_price} />
                    </td>
                    <td>
                      {t.exit_price === null ? (
                        <Unknown kind="not-scorable" note="Position is still open" />
                      ) : (
                        <Num value={t.exit_price} />
                      )}
                    </td>
                    <td>
                      <Money
                        value={t.realized_pnl}
                        signed
                        kind="not-scorable"
                        note="Not realized until the position closes"
                      />
                    </td>
                    <td>
                      {/* R requires a stop; without one the trade is genuinely
                          not scorable in R terms, which is not the same as 0R. */}
                      <Num
                        value={t.r_multiple}
                        digits={2}
                        suffix="R"
                        kind="not-scorable"
                        note="No stop price was recorded, so risk-multiple is undefined"
                      />
                    </td>
                    <td>
                      <span className={`badge ${t.status === "open" ? "" : "badge-ok"}`}>
                        {t.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loaded>
    </>
  );
}
