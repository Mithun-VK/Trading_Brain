"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api";
import type { ResearchAnalysis } from "@/lib/types";
import { ErrorBox } from "@/components/ErrorBox";

export function ResearchPanel({ initialTicker }: { initialTicker?: string }) {
  const [ticker, setTicker] = useState(initialTicker ?? "");
  const [analysis, setAnalysis] = useState<ResearchAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    const target = (initialTicker ?? ticker).trim();
    if (!target) return;
    setLoading(true);
    setError(null);
    setAnalysis(null);

    const result = await apiPost<ResearchAnalysis>(`/research/${encodeURIComponent(target)}`);
    if (result.ok) {
      setAnalysis(result.data);
    } else {
      setError(result.error);
    }
    setLoading(false);
  }

  return (
    <div>
      <form className="inline-form" onSubmit={run}>
        {!initialTicker && (
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="Ticker, e.g. RELIANCE"
          />
        )}
        <button type="submit" disabled={loading}>
          {loading ? "Running Research Agent…" : "Generate research"}
        </button>
      </form>

      {error && <ErrorBox message={error} />}

      {analysis && (
        <div className="card">
          <span className="badge">confidence {analysis.confidence.toFixed(2)}</span>
          <h2 style={{ marginTop: "0.6rem" }}>Summary</h2>
          <p>{analysis.summary}</p>

          <EvidenceList title="Positive factors" items={analysis.positive_factors} />
          <EvidenceList title="Negative factors" items={analysis.negative_factors} />
          <EvidenceList title="Contradictions" items={analysis.contradictions} />
          <EvidenceList title="Risks" items={analysis.risks} />
          <EvidenceList title="Catalysts" items={analysis.catalysts} />

          <p className="muted" style={{ fontSize: "0.8rem", marginTop: "0.6rem" }}>
            Not guaranteed financial advice or a guaranteed prediction. Published to Obsidian
            under 08 Research/.
          </p>
        </div>
      )}
    </div>
  );
}

function EvidenceList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      <h2>{title}</h2>
      <ul className="bulleted">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </>
  );
}
