import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { SignalLineageOut } from "@/lib/types";
import { Loaded } from "@/components/Section";

export const dynamic = "force-dynamic";

const STAGE_LABEL: Record<string, string> = {
  market_data: "Market data",
  regime: "Market regime",
  research: "Research",
  thesis: "Thesis",
  signal: "Signal",
  paper_trade: "Paper trade",
};

export default async function SignalLineagePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const lineage = await apiGet<SignalLineageOut>(`/lineage/signals/${id}`);

  return (
    <>
      <h1>Signal provenance</h1>
      <p className="lede">
        Every input this signal was derived from. A stage marked{" "}
        <em>not recorded</em> is a genuine gap in the chain — the system does not fill one in, since
        an invented provenance is worse than a missing one.
      </p>

      <Loaded result={lineage} what={`lineage for signal ${id}`}>
        {(d) => (
          <>
            <ol className="lineage">
              {d.chain.map((node) => (
                <li key={node.stage} className={node.recorded ? "recorded" : "not-recorded"}>
                  <div className="lineage-stage">
                    {STAGE_LABEL[node.stage] ?? node.stage}
                    {node.recorded ? null : <span className="badge"> not recorded</span>}
                  </div>
                  <div className="lineage-summary">{node.summary}</div>
                </li>
              ))}
            </ol>

            <h2>Evidence</h2>
            <ul className="plain">
              {d.evidence.map((e, i) => (
                <li key={i}>
                  <span className={`stance stance-${e.stance}`}>
                    {e.stance === "supports" ? "+" : e.stance === "contradicts" ? "−" : "·"}
                  </span>{" "}
                  <span className="evidence-kind">{e.kind}</span> {e.detail}
                </li>
              ))}
            </ul>

            <p style={{ marginTop: "1.5rem" }}>
              <Link className="link" href="/signals">
                ← Back to signals
              </Link>
            </p>
          </>
        )}
      </Loaded>
    </>
  );
}
