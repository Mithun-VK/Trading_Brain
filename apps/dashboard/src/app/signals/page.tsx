import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { SignalOut } from "@/lib/types";
import { Loaded } from "@/components/Section";
import { Pct, Unknown } from "@/components/Value";

export const dynamic = "force-dynamic";

// Categories are advisory. There is deliberately no BUY or SELL: the signal
// engine rejects execution categories at construction time, and the UI
// should not imply an action the system cannot take.
const CATEGORY_MEANING: Record<string, string> = {
  WATCH: "Worth monitoring. No action implied.",
  RESEARCH: "Something changed that warrants reading, not trading.",
  ACCUMULATE: "Conditions favour adding — for your judgement, not automatic.",
  REDUCE: "Conditions favour trimming — for your judgement, not automatic.",
  EXIT_REVIEW: "Reconsider holding this position.",
  THESIS_REVIEW: "The thesis itself may no longer hold.",
};

function StanceIcon({ stance }: { stance: string }) {
  const symbol = stance === "supports" ? "+" : stance === "contradicts" ? "−" : "·";
  return (
    <span className={`stance stance-${stance}`} title={stance}>
      {symbol}
    </span>
  );
}

function SignalCard({ signal }: { signal: SignalOut }) {
  const supports = signal.evidence.filter((e) => e.stance === "supports").length;
  const contradicts = signal.evidence.filter((e) => e.stance === "contradicts").length;

  return (
    <article className="card signal-card">
      <header className="signal-head">
        <div>
          <span className={`badge cat-${signal.category.toLowerCase()}`}>{signal.category}</span>{" "}
          <strong>{signal.ticker}</strong>
        </div>
        <div className="signal-confidence">
          confidence <Pct value={signal.confidence} digits={0} />
        </div>
      </header>

      <p className="muted small">{CATEGORY_MEANING[signal.category] ?? "Advisory only."}</p>

      {signal.reasoning ? <p className="signal-reasoning">{signal.reasoning}</p> : null}

      {/* Evidence is never empty -- the API refuses to serve a signal without
          it (Rule 10). Showing the supporting/contradicting split matters:
          a high-confidence signal that also carries contradicting evidence
          is a different thing from an unopposed one. */}
      <div className="evidence">
        <div className="evidence-head">
          Evidence — {supports} supporting, {contradicts} contradicting
        </div>
        <ul className="plain">
          {signal.evidence.map((e, i) => (
            <li key={i}>
              <StanceIcon stance={e.stance} /> <span className="evidence-kind">{e.kind}</span>{" "}
              {e.detail}
              {e.value !== null && e.value !== undefined ? (
                <span className="muted"> ({String(e.value)})</span>
              ) : null}
            </li>
          ))}
        </ul>
      </div>

      <footer className="signal-foot">
        <span>
          Regime at signal time:{" "}
          {signal.market_regime ?? <Unknown note="No regime observation was recorded then" />}
        </span>
        <span>
          Thesis: {signal.thesis_assessment ?? <Unknown note="No thesis exists for this asset" />}
        </span>
        <span>{new Date(signal.generated_at).toLocaleString()}</span>
        <Link className="link" href={`/lineage/signal/${signal.id}`}>
          Provenance →
        </Link>
      </footer>
    </article>
  );
}

export default async function SignalsPage() {
  const signals = await apiGet<SignalOut[]>("/signals?limit=50");

  return (
    <>
      <h1>Signals</h1>
      <p className="lede">
        Evidence-backed observations. Every signal here is advisory: TradingBrain has no execution
        path, and no category in this system corresponds to placing an order.
      </p>

      <Loaded
        result={signals}
        what="signals"
        isEmpty={(d) => d.length === 0}
        empty="No signals generated yet. The signal engine runs after market data and thesis reviews are in place."
      >
        {(data) => (
          <>
            {data.map((s) => (
              <SignalCard key={s.id} signal={s} />
            ))}
          </>
        )}
      </Loaded>
    </>
  );
}
