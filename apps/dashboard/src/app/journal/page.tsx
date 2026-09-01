"use client";

import { Fragment, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import type { JournalReview, TradeIn, TradeOut } from "@/lib/types";
import { ErrorBox } from "@/components/ErrorBox";

const EMPTY_FORM: TradeIn = {
  ticker: "",
  direction: "long",
  timeframe: "1d",
  entry_price: 0,
  stop_price: 0,
  risk_amount: 0,
  position_size: 0,
  opened_at: new Date().toISOString(),
};

export default function JournalPage() {
  const [trades, setTrades] = useState<TradeOut[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [form, setForm] = useState<TradeIn>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [reviewByTrade, setReviewByTrade] = useState<Record<number, JournalReview>>({});
  const [reviewingId, setReviewingId] = useState<number | null>(null);

  async function loadTrades() {
    const result = await apiGet<TradeOut[]>("/trades");
    if (result.ok) {
      setTrades(result.data);
      setListError(null);
    } else {
      setListError(result.error);
    }
  }

  useEffect(() => {
    loadTrades();
  }, []);

  async function submitTrade(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);

    const result = await apiPost<TradeOut>("/trades", form);
    if (result.ok) {
      setForm(EMPTY_FORM);
      await loadTrades();
    } else {
      setFormError(result.error);
    }
    setSubmitting(false);
  }

  async function reviewTrade(id: number) {
    setReviewingId(id);
    const result = await apiPost<JournalReview>(`/trades/${id}/review`);
    if (result.ok) {
      setReviewByTrade((prev) => ({ ...prev, [id]: result.data }));
    } else {
      setListError(result.error);
    }
    setReviewingId(null);
  }

  return (
    <>
      <h1>Trading Journal</h1>
      <p className="lede">
        Journals trades you already made or planned — this does not place any order. Broker
        execution does not exist in this system.
      </p>

      <h2>Record a trade</h2>
      <form className="card" onSubmit={submitTrade}>
        <div className="card-grid">
          <input
            placeholder="Ticker"
            value={form.ticker}
            onChange={(e) => setForm({ ...form, ticker: e.target.value })}
            required
          />
          <select
            value={form.direction}
            onChange={(e) => setForm({ ...form, direction: e.target.value })}
          >
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
          <input
            placeholder="Strategy (optional)"
            value={form.strategy_name ?? ""}
            onChange={(e) => setForm({ ...form, strategy_name: e.target.value || undefined })}
          />
          <input
            placeholder="Timeframe, e.g. 1d"
            value={form.timeframe}
            onChange={(e) => setForm({ ...form, timeframe: e.target.value })}
            required
          />
          <input
            type="number"
            step="any"
            placeholder="Entry price"
            value={form.entry_price || ""}
            onChange={(e) => setForm({ ...form, entry_price: Number(e.target.value) })}
            required
          />
          <input
            type="number"
            step="any"
            placeholder="Stop price"
            value={form.stop_price || ""}
            onChange={(e) => setForm({ ...form, stop_price: Number(e.target.value) })}
            required
          />
          <input
            type="number"
            step="any"
            placeholder="Risk amount"
            value={form.risk_amount || ""}
            onChange={(e) => setForm({ ...form, risk_amount: Number(e.target.value) })}
            required
          />
          <input
            type="number"
            step="any"
            placeholder="Position size"
            value={form.position_size || ""}
            onChange={(e) => setForm({ ...form, position_size: Number(e.target.value) })}
            required
          />
        </div>
        <button type="submit" disabled={submitting} style={{ marginTop: "0.8rem" }}>
          {submitting ? "Saving…" : "Save trade"}
        </button>
        {formError && <ErrorBox message={formError} />}
      </form>

      <h2>Trades</h2>
      {listError && <ErrorBox message={listError} />}
      {trades === null ? (
        <p className="muted">Loading…</p>
      ) : trades.length === 0 ? (
        <p className="muted">No trades recorded yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Dir</th>
              <th>Status</th>
              <th>Result</th>
              <th>R</th>
              <th>Opened</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <Fragment key={trade.id}>
                <tr>
                  <td>{trade.ticker}</td>
                  <td>{trade.direction}</td>
                  <td>{trade.status}</td>
                  <td>{trade.result ?? "—"}</td>
                  <td>{trade.r_multiple ?? "—"}</td>
                  <td>{new Date(trade.opened_at).toLocaleDateString()}</td>
                  <td>
                    <button
                      className="secondary"
                      onClick={() => reviewTrade(trade.id)}
                      disabled={reviewingId === trade.id}
                    >
                      {reviewingId === trade.id ? "Reviewing…" : "Review"}
                    </button>
                  </td>
                </tr>
                {reviewByTrade[trade.id] && (
                  <tr>
                    <td colSpan={7}>
                      <div className="card" style={{ margin: "0.4rem 0" }}>
                        {reviewByTrade[trade.id].patterns.map((p, i) => (
                          <div key={i}>• {p}</div>
                        ))}
                        {reviewByTrade[trade.id].overall.sample_size_warning && (
                          <p className="muted" style={{ fontSize: "0.8rem" }}>
                            ⚠ {reviewByTrade[trade.id].overall.sample_size_warning}
                          </p>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
