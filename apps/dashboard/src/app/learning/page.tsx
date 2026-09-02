import { apiGetAll } from "@/lib/api";
import type { LearningReportOut, LearningSummaryOut } from "@/lib/types";
import { EmptyState, ErrorBox } from "@/components/Section";
import { Num, Pct, SampledMetric, Unknown } from "@/components/Value";

export const dynamic = "force-dynamic";

export default async function LearningPage() {
  const [summary, reports] = await apiGetAll<[LearningSummaryOut, LearningReportOut[]]>(
    "/learning/summary",
    "/learning/reports?limit=12",
  );

  return (
    <>
      <h1>Learning</h1>
      <p className="lede">
        How well this system has actually reasoned, measured against recorded outcomes. Small
        samples are labelled as such rather than rounded into confidence.
      </p>

      {!summary.ok ? (
        <ErrorBox message={summary.error} what="the learning summary" />
      ) : !summary.data.available ? (
        <EmptyState>{summary.data.reason}</EmptyState>
      ) : (
        <>
          <p className="muted small">
            Period {summary.data.period_start} to {summary.data.period_end}, generated{" "}
            {new Date(summary.data.generated_at).toLocaleString()}.
          </p>

          <div className="card-grid">
            <SampledMetric
              label="Signal accuracy"
              value={summary.data.signal_accuracy}
              sampleSize={summary.data.signal_sample_size}
              isSignificant={summary.data.signal_is_significant}
              caveat={summary.data.signal_caveat}
            />

            <div className="card">
              <div className="stat-label">Theses tracked</div>
              <div className="stat-value">
                <Num value={summary.data.theses_tracked} digits={0} />
              </div>
            </div>

            <div className="card">
              <div className="stat-label">Invalidation rate</div>
              <div className="stat-value">
                <Pct value={summary.data.invalidation_rate} />
              </div>
              <div className="stat-caveat">
                Share of theses that were later invalidated. Higher is not automatically worse — it
                can mean invalidation conditions were written sharply enough to trigger.
              </div>
            </div>

            <div className="card">
              <div className="stat-label">Median days to invalidation</div>
              <div className="stat-value">
                <Num value={summary.data.median_days_to_invalidation} digits={0} suffix=" days" />
              </div>
            </div>
          </div>

          {/* Research outcomes are explicitly not an accuracy score, and the
              API says so in a field. Rendering it beside the accuracy cards
              without that distinction would be the exact mistake the backend
              is guarding against. */}
          <h2>Research outcomes</h2>
          <div className="card">
            {summary.data.research_is_accuracy_score ? (
              <p>Research outcomes are being scored for accuracy this period.</p>
            ) : (
              <>
                <div className="stat-value">
                  <Unknown
                    kind="not-scorable"
                    note="Research outcomes are tracked but are not an accuracy measure"
                  />
                </div>
                <p className="stat-caveat">
                  {summary.data.research_note ??
                    "Research outcomes are recorded but not scored as correct or incorrect."}
                </p>
              </>
            )}
          </div>
        </>
      )}

      <h2>Reports</h2>
      {!reports.ok ? (
        <ErrorBox message={reports.error} what="learning reports" />
      ) : reports.data.length === 0 ? (
        <EmptyState>No learning review has been generated yet.</EmptyState>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Kind</th>
                <th>Period</th>
                <th>Generated</th>
                <th>Vault note</th>
              </tr>
            </thead>
            <tbody>
              {reports.data.map((r) => (
                <tr key={r.id}>
                  <td>{r.kind}</td>
                  <td>
                    {r.period_start} → {r.period_end}
                  </td>
                  <td>{new Date(r.generated_at).toLocaleDateString()}</td>
                  <td>
                    {r.obsidian_note_path ?? (
                      <Unknown note="This report was not published to the vault" />
                    )}
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
