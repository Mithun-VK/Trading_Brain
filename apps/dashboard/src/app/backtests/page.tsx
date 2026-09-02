import { apiGet } from "@/lib/api";
import type { BacktestOut } from "@/lib/types";
import { Loaded } from "@/components/Section";
import { Num, Pct } from "@/components/Value";

export const dynamic = "force-dynamic";

export default async function BacktestsPage() {
  const runs = await apiGet<BacktestOut[]>("/backtests?limit=50");

  return (
    <>
      <h1>Backtests</h1>
      <p className="lede">
        Historical simulations. Fills occur at the next bar&apos;s open and strategies only ever see
        data up to the current bar, so results here cannot contain lookahead — but they are still
        simulations, and past behaviour is not a forecast.
      </p>

      <Loaded
        result={runs}
        what="backtest runs"
        isEmpty={(d) => d.length === 0}
        empty="No backtests have been run yet."
      >
        {(data) => (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th>Ticker</th>
                  <th>Period</th>
                  <th>Trades</th>
                  <th>Return</th>
                  <th>CAGR</th>
                  <th>Sharpe</th>
                  <th>Max DD</th>
                  <th>Win rate</th>
                </tr>
              </thead>
              <tbody>
                {data.map((r) => {
                  // A run that produced no trades has no return to report.
                  // Rendering 0.00% would read as "the strategy broke even"
                  // when in fact it never traded.
                  const noTrades = r.trade_count === 0;
                  return (
                    <tr key={r.id}>
                      <td>{r.strategy}</td>
                      <td>
                        <strong>{r.ticker}</strong>
                      </td>
                      <td className="small muted">
                        {r.start_date} → {r.end_date}
                      </td>
                      <td>{r.trade_count}</td>
                      <td>
                        <Pct
                          value={noTrades ? null : r.total_return}
                          signed
                          kind="not-scorable"
                          note="The strategy generated no trades in this period"
                        />
                      </td>
                      <td>
                        <Pct value={noTrades ? null : r.cagr} signed kind="not-scorable" />
                      </td>
                      <td>
                        <Num value={noTrades ? null : r.sharpe} kind="not-scorable" />
                      </td>
                      <td>
                        <Pct value={noTrades ? null : r.max_drawdown} kind="not-scorable" />
                      </td>
                      <td>
                        <Pct value={noTrades ? null : r.win_rate} kind="not-scorable" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Loaded>
    </>
  );
}
