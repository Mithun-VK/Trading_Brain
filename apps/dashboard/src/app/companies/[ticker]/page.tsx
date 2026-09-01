import { apiGet } from "@/lib/api";
import type { AnalysisOut, AssetOut } from "@/lib/types";
import { ErrorBox } from "@/components/ErrorBox";
import { ResearchPanel } from "@/components/ResearchPanel";

export default async function CompanyPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  const [asset, analysis] = await Promise.all([
    apiGet<AssetOut>(`/assets/${encodeURIComponent(ticker)}`),
    apiGet<AnalysisOut>(`/analysis/${encodeURIComponent(ticker)}`),
  ]);

  return (
    <>
      <h1>{ticker}</h1>

      {asset.ok ? (
        <div className="card">
          <div className="card-grid">
            <Field label="Name" value={asset.data.name} />
            <Field label="Exchange" value={asset.data.exchange} />
            <Field label="Type" value={asset.data.asset_type} />
            <Field label="Currency" value={asset.data.currency} />
            <Field label="Sector" value={asset.data.sector ?? "—"} />
            <Field label="Industry" value={asset.data.industry ?? "—"} />
          </div>
        </div>
      ) : (
        <ErrorBox message={asset.error} />
      )}

      <h2>Deterministic quant summary</h2>
      {analysis.ok ? (
        Object.keys(analysis.data.quant_summary).length > 0 ? (
          <div className="card-grid">
            {Object.entries(analysis.data.quant_summary).map(([key, value]) => (
              <div className="card" key={key}>
                <div className="stat-label">{key}</div>
                <div className="stat-value">{String(value)}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">No price history available for this ticker.</p>
        )
      ) : (
        <ErrorBox message={analysis.error} />
      )}

      <h2>Research</h2>
      <ResearchPanel initialTicker={ticker} />
    </>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="stat-label">{label}</div>
      <div style={{ marginTop: "0.15rem" }}>{value}</div>
    </div>
  );
}
