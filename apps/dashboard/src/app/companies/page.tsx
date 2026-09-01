"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function CompaniesSearchPage() {
  const [ticker, setTicker] = useState("");
  const router = useRouter();

  function go(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = ticker.trim();
    if (!trimmed) return;
    router.push(`/companies/${encodeURIComponent(trimmed)}`);
  }

  return (
    <>
      <h1>Companies</h1>
      <p className="lede">
        Look up a ticker to see its asset metadata and deterministic quant analysis.
      </p>
      <form className="inline-form" onSubmit={go}>
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="Ticker, e.g. RELIANCE"
        />
        <button type="submit">View</button>
      </form>
    </>
  );
}
