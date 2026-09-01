"use client";

import { useState } from "react";
import { apiGet } from "@/lib/api";
import type { QuoteOut } from "@/lib/types";
import { ErrorBox } from "@/components/ErrorBox";

export function QuoteLookup() {
  const [ticker, setTicker] = useState("");
  const [quote, setQuote] = useState<QuoteOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function lookup(e: React.FormEvent) {
    e.preventDefault();
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    setQuote(null);

    const result = await apiGet<QuoteOut>(`/market/${encodeURIComponent(ticker.trim())}`);
    if (result.ok) {
      setQuote(result.data);
    } else {
      setError(result.error);
    }
    setLoading(false);
  }

  return (
    <div>
      <form className="inline-form" onSubmit={lookup}>
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="Ticker, e.g. RELIANCE"
        />
        <button type="submit" disabled={loading}>
          {loading ? "Looking up…" : "Get quote"}
        </button>
      </form>

      {error && <ErrorBox message={error} />}

      {quote && (
        <div className="card">
          <div className="stat-label">{quote.ticker}</div>
          <div className="stat-value">{quote.price.toFixed(2)}</div>
          <div className={quote.change >= 0 ? "muted" : "muted"}>
            {quote.change >= 0 ? "+" : ""}
            {quote.change.toFixed(2)} ({quote.change_percent.toFixed(2)}%) · vol {quote.volume}
          </div>
          <div className="muted" style={{ fontSize: "0.8rem", marginTop: "0.4rem" }}>
            source: {quote.source} · as of {new Date(quote.as_of).toLocaleString()}
          </div>
        </div>
      )}
    </div>
  );
}
