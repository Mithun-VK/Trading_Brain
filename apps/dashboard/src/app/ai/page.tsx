import { apiGetAll } from "@/lib/api";
import type { AIBudgetOut, AIStatusOut, AIUsageBucket, AIUsageOut } from "@/lib/types";
import { EmptyState, ErrorBox } from "@/components/Section";
import { Money, Num, Pct, Stat, Unknown } from "@/components/Value";

export const dynamic = "force-dynamic";

/** An estimate derived from recorded token counts — never a billing figure,
 *  and null when nothing priced was recorded rather than zero. */
function Cost({ value }: { value: number | null }) {
  if (value === null) {
    return <Unknown note="Nothing priced has been recorded in this window" />;
  }
  return <Money value={value} currency="USD" />;
}

function BucketTable({ title, rows }: { title: string; rows: AIUsageBucket[] }) {
  return (
    <>
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <EmptyState>Nothing recorded.</EmptyState>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Key</th>
                <th>Calls</th>
                <th>Input</th>
                <th>Output</th>
                <th>Estimated cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.key ?? "unknown"}-${i}`}>
                  <td className="mono small">{row.key ?? <Unknown />}</td>
                  <td>
                    <Num value={row.calls} digits={0} />
                  </td>
                  <td>
                    <Num value={row.input_tokens} digits={0} />
                  </td>
                  <td>
                    <Num value={row.output_tokens} digits={0} />
                  </td>
                  <td>
                    <Cost value={row.estimated_cost} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function budgetTone(state: string): string {
  if (state === "healthy") return "status-healthy";
  if (state === "exceeded") return "status-unavailable";
  return "status-degraded";
}

export default async function AIOperationsPage() {
  const [status, usage, budget] = await apiGetAll<[AIStatusOut, AIUsageOut, AIBudgetOut]>(
    "/ai/status",
    "/ai/usage?hours=24",
    "/ai/budget",
  );

  return (
    <>
      <h1>AI Operations</h1>
      <p className="lede">
        What the reasoning layer did, what it cost, and what it was stopped from doing.
        Deterministic analysis — indicators, risk, portfolio maths, backtests — runs with no AI at
        all and is deliberately not counted here.
      </p>

      <h2>Providers</h2>
      {!status.ok ? (
        <ErrorBox message={status.error} what="AI status" />
      ) : !status.data.enabled ? (
        <EmptyState>
          No AI provider is configured. Set <code>ANTHROPIC_API_KEY</code> or{" "}
          <code>LOCAL_LLM_BASE_URL</code> to enable the reasoning layer. Every deterministic part
          of TradingBrain works without it.
        </EmptyState>
      ) : status.data.providers.length === 0 ? (
        <EmptyState>AI is enabled but no provider is registered.</EmptyState>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Tier</th>
                <th>State</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {status.data.providers.map((p) => (
                <tr key={p.name}>
                  <td>
                    <strong>{p.name}</strong>
                  </td>
                  <td className="mono small">{p.tier}</td>
                  <td>
                    <span
                      className={`badge ${
                        p.available ? "status-healthy" : "status-unavailable"
                      }`}
                    >
                      {p.available ? "available" : "unavailable"}
                    </span>
                  </td>
                  <td className="small">{p.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Last 24 hours</h2>
      {!usage.ok ? (
        <ErrorBox message={usage.error} what="AI usage" />
      ) : !usage.data.recorded ? (
        <EmptyState>
          {usage.data.reason} Nothing has run — which is not the same as AI having run and cost
          nothing.
        </EmptyState>
      ) : (
        <>
          <div className="card-grid">
            <Stat label="Calls">
              <Num value={usage.data.calls} digits={0} />
            </Stat>
            <Stat
              label="Estimated spend"
              caveat={
                usage.data.calls_with_unknown_cost
                  ? `${usage.data.calls_with_unknown_cost} call(s) reported no usage figures, so this is a floor, not a total`
                  : null
              }
            >
              <Cost value={usage.data.estimated_cost} />
            </Stat>
            <Stat label="Local / frontier" caveat="Calls handled locally versus sent to a frontier model">
              <span className="num">
                {usage.data.local_calls} / {usage.data.frontier_calls}
              </span>
            </Stat>
            <Stat label="Escalation rate" caveat="Share of calls routed above their base tier">
              <Pct value={usage.data.escalation_rate} />
            </Stat>
            <Stat label="Cache hit rate">
              <Pct value={usage.data.cache_hit_rate} />
            </Stat>
            <Stat label="Failed / blocked">
              <span className="num">
                {usage.data.failed} / {usage.data.blocked}
              </span>
            </Stat>
            <Stat label="Input tokens">
              <Num value={usage.data.input_tokens} digits={0} />
            </Stat>
            <Stat label="Output tokens">
              <Num value={usage.data.output_tokens} digits={0} />
            </Stat>
          </div>

          <BucketTable title="Top tasks by cost" rows={usage.data.by_task} />
          <BucketTable title="By model" rows={usage.data.by_model} />
          <BucketTable title="By provider" rows={usage.data.by_provider} />
        </>
      )}

      <h2>Budget</h2>
      {!budget.ok ? (
        <ErrorBox message={budget.error} what="AI budget" />
      ) : budget.data.windows.length === 0 ? (
        <EmptyState>
          No AI budget is configured. Set <code>AI_BUDGET_DAY_USD</code> (and the hour/month
          equivalents) to cap spending — without one, only rate limits bound cost.
        </EmptyState>
      ) : (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Window</th>
                  <th>State</th>
                  <th>Spent</th>
                  <th>Limit</th>
                  <th>Remaining</th>
                </tr>
              </thead>
              <tbody>
                {budget.data.windows.map((w) => (
                  <tr key={w.window}>
                    <td>{w.window}</td>
                    <td>
                      <span className={`badge ${budgetTone(w.state)}`}>{w.state}</span>
                    </td>
                    <td>
                      <Cost value={w.spent} />
                    </td>
                    <td>
                      <Cost value={w.limit} />
                    </td>
                    <td>
                      <Cost value={w.remaining} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="stat-caveat" style={{ marginTop: "0.6rem" }}>
            {budget.data.note}
          </p>
        </>
      )}
    </>
  );
}
