"use client";

import { useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import type { ThesisOut, ThesisReview } from "@/lib/types";
import { ErrorBox } from "@/components/ErrorBox";

export default function ThesesPage() {
  const [ticker, setTicker] = useState("");
  const [thesis, setThesis] = useState<ThesisOut | null>(null);
  const [review, setReview] = useState<ThesisReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reviewing, setReviewing] = useState(false);

  async function lookup(e: React.FormEvent) {
    e.preventDefault();
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    setThesis(null);
    setReview(null);

    const result = await apiGet<ThesisOut>(`/thesis/${encodeURIComponent(ticker.trim())}`);
    if (result.ok) {
      setThesis(result.data);
    } else {
      setError(result.error);
    }
    setLoading(false);
  }

  async function runReview() {
    setReviewing(true);
    setError(null);
    const result = await apiPost<ThesisReview>(`/thesis/${encodeURIComponent(ticker.trim())}/review`);
    if (result.ok) {
      setReview(result.data);
      setThesis((prev) => (prev ? { ...prev, current_assessment: result.data.assessment } : prev));
    } else {
      setError(result.error);
    }
    setReviewing(false);
  }

  return (
    <>
      <h1>Investment Theses</h1>
      <p className="lede">
        Thesis changes are always auditable — a review never overwrites a thesis note; it
        appends a dated entry to Historical Changes.
      </p>

      <form className="inline-form" onSubmit={lookup}>
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="Ticker, e.g. RELIANCE"
        />
        <button type="submit" disabled={loading}>
          {loading ? "Looking up…" : "Find active thesis"}
        </button>
      </form>

      {error && <ErrorBox message={error} />}

      {thesis && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>{thesis.title}</h2>
          <div className="card-grid">
            <div>
              <div className="stat-label">Status</div>
              <div>{thesis.status}</div>
            </div>
            <div>
              <div className="stat-label">Current assessment</div>
              <div>{thesis.current_assessment}</div>
            </div>
            <div>
              <div className="stat-label">Conviction</div>
              <div>{thesis.conviction ?? "—"}</div>
            </div>
            <div>
              <div className="stat-label">Last reviewed</div>
              <div>{thesis.last_reviewed_at ? new Date(thesis.last_reviewed_at).toLocaleDateString() : "never"}</div>
            </div>
          </div>
          <button style={{ marginTop: "0.8rem" }} onClick={runReview} disabled={reviewing}>
            {reviewing ? "Running Thesis Agent…" : "Run review"}
          </button>
        </div>
      )}

      {review && (
        <div className="card">
          <span className="badge">confidence {review.confidence.toFixed(2)}</span>
          <h2 style={{ marginTop: "0.6rem" }}>
            {review.previous_assessment} → {review.assessment}
          </h2>
          <p>{review.reasoning}</p>
          <EvidenceList title="Supporting evidence" items={review.supporting_evidence} />
          <EvidenceList title="Contradicting evidence" items={review.contradicting_evidence} />
          <EvidenceList title="Changed assumptions" items={review.changed_assumptions} />
          <EvidenceList
            title="Invalidation conditions triggered"
            items={review.invalidation_conditions_triggered}
          />
        </div>
      )}
    </>
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
