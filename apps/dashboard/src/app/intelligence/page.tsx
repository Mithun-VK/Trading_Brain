import { apiGet } from "@/lib/api";
import type { ResearchQueueOut } from "@/lib/types";
import { Loaded } from "@/components/Section";
import { Num } from "@/components/Value";

export const dynamic = "force-dynamic";

/** The queue score is a weighted blend. Showing only the total would make
 *  the ordering look arbitrary; showing the components makes it arguable. */
function ScoreBreakdown({ entry }: { entry: ResearchQueueOut }) {
  const parts = [
    { label: "Importance", value: entry.importance },
    { label: "Novelty", value: entry.novelty },
    { label: "Portfolio impact", value: entry.portfolio_impact },
    { label: "Watchlist relevance", value: entry.watchlist_relevance },
  ];
  return (
    <div className="score-bars">
      {parts.map((p) => (
        <div key={p.label} className="score-bar">
          <span className="score-bar-label">{p.label}</span>
          <span className="score-bar-track">
            <span
              className="score-bar-fill"
              style={{ width: `${Math.max(0, Math.min(1, p.value)) * 100}%` }}
            />
          </span>
          <span className="score-bar-value">
            <Num value={p.value} digits={2} />
          </span>
        </div>
      ))}
    </div>
  );
}

export default async function IntelligencePage() {
  const queue = await apiGet<ResearchQueueOut[]>("/research/queue?status=pending&limit=50");

  return (
    <>
      <h1>Research Queue</h1>
      <p className="lede">
        Detected changes ranked by how much they should change your mind, highest first. Processing
        an entry runs the Research Agent and costs a Claude API call, so it is never automatic.
      </p>

      <Loaded
        result={queue}
        what="queue entries"
        isEmpty={(d) => d.length === 0}
        empty="Nothing queued. Either no material change has been detected, or ingestion has not run yet — check System health to tell those apart."
      >
        {(data) => (
          <>
            {data.map((entry) => (
              <article key={entry.id} className="card queue-card">
                <header className="queue-head">
                  <div>
                    <strong>{entry.ticker}</strong>{" "}
                    <span className="badge">{entry.change_type}</span>
                  </div>
                  <div className="queue-score">
                    priority <Num value={entry.score} digits={2} />
                  </div>
                </header>

                {entry.reasons.length > 0 ? (
                  <ul className="bulleted small">
                    {entry.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted small">No reasons were recorded for this entry.</p>
                )}

                <ScoreBreakdown entry={entry} />

                <footer className="queue-foot muted small">
                  Detected {new Date(entry.detected_at).toLocaleString()}
                </footer>
              </article>
            ))}
          </>
        )}
      </Loaded>
    </>
  );
}
