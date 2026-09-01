"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const STORAGE_KEY = "tradingbrain.watchlist";

export default function WatchlistPage() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) setTickers(JSON.parse(stored) as string[]);
    } catch {
      // localStorage unavailable (private browsing, etc.) -- just start empty.
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tickers));
    } catch {
      // ignore
    }
  }, [tickers, loaded]);

  function add(e: React.FormEvent) {
    e.preventDefault();
    const ticker = input.trim().toUpperCase();
    if (!ticker || tickers.includes(ticker)) return;
    setTickers([...tickers, ticker]);
    setInput("");
  }

  function remove(ticker: string) {
    setTickers(tickers.filter((t) => t !== ticker));
  }

  return (
    <>
      <h1>Watchlist</h1>
      <p className="lede">
        Stored locally in this browser only — TradingBrain has no watchlist table in the
        database yet. Clearing your browser storage clears this list.
      </p>

      <form className="inline-form" onSubmit={add}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Add ticker, e.g. TCS"
        />
        <button type="submit">Add</button>
      </form>

      {tickers.length === 0 ? (
        <p className="muted">No tickers yet.</p>
      ) : (
        <ul className="plain">
          {tickers.map((ticker) => (
            <li key={ticker} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Link href={`/companies/${encodeURIComponent(ticker)}`}>{ticker}</Link>
              <button className="secondary" onClick={() => remove(ticker)}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
