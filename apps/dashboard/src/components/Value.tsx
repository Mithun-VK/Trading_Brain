// Display primitives for values that may not be knowable.
//
// The API goes to deliberate trouble to return `null` rather than `0.0`
// when something has not been observed -- a portfolio with one snapshot has
// no daily return, and reporting 0.0 would claim a flat day that never
// happened. A dashboard that renders that null as "0.00" or a bare dash
// throws away the distinction the backend worked to preserve.
//
// So "unknown" is a first-class rendering state here, and there are four
// different reasons a number can be absent. They look different on screen
// on purpose:
//
//   unrecorded    -- nothing has been observed yet
//   insufficient  -- observed, but too few samples to mean anything
//   not-scorable  -- the thing is real but this metric does not apply to it
//   unpriced      -- a market price was unavailable, so it is excluded
//
// None of these is zero, and none of them is a failure.

export type UnknownKind = "unrecorded" | "insufficient" | "not-scorable" | "unpriced";

const UNKNOWN_LABEL: Record<UnknownKind, string> = {
  unrecorded: "Not recorded",
  insufficient: "Insufficient sample",
  "not-scorable": "Not scorable",
  unpriced: "No price",
};

export function Unknown({ kind = "unrecorded", note }: { kind?: UnknownKind; note?: string }) {
  return (
    <span className={`unknown unknown-${kind}`} title={note ?? UNKNOWN_LABEL[kind]}>
      {UNKNOWN_LABEL[kind]}
    </span>
  );
}

type Maybe = number | null | undefined;

function isKnown(value: Maybe): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** A plain number, or an explicit unknown marker. */
export function Num({
  value,
  digits = 2,
  suffix,
  kind,
  note,
}: {
  value: Maybe;
  digits?: number;
  suffix?: string;
  kind?: UnknownKind;
  note?: string;
}) {
  if (!isKnown(value)) return <Unknown kind={kind} note={note} />;
  return (
    <span className="num">
      {value.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })}
      {suffix}
    </span>
  );
}

/** A ratio rendered as a percentage. Input is a fraction (0.12 -> 12.00%). */
export function Pct({
  value,
  digits = 2,
  signed = false,
  kind,
  note,
}: {
  value: Maybe;
  digits?: number;
  signed?: boolean;
  kind?: UnknownKind;
  note?: string;
}) {
  if (!isKnown(value)) return <Unknown kind={kind} note={note} />;
  const pct = value * 100;
  const cls = signed ? (pct > 0 ? "pos" : pct < 0 ? "neg" : "") : "";
  return (
    <span className={`num ${cls}`}>
      {signed && pct > 0 ? "+" : ""}
      {pct.toFixed(digits)}%
    </span>
  );
}

/** A currency-ish amount. No symbol is hard-coded: the base currency comes
 *  from the portfolio, and inventing "$" would be a fabricated fact. */
export function Money({
  value,
  currency,
  signed = false,
  kind,
  note,
}: {
  value: Maybe;
  currency?: string;
  signed?: boolean;
  kind?: UnknownKind;
  note?: string;
}) {
  if (!isKnown(value)) return <Unknown kind={kind} note={note} />;
  const cls = signed ? (value > 0 ? "pos" : value < 0 ? "neg" : "") : "";
  return (
    <span className={`num ${cls}`}>
      {signed && value > 0 ? "+" : ""}
      {value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      {currency ? <span className="currency"> {currency}</span> : null}
    </span>
  );
}

/** A headline stat in a card. `caveat` renders beneath in muted text --
 *  the API attaches caveats to numbers, and they belong next to them. */
export function Stat({
  label,
  children,
  caveat,
}: {
  label: string;
  children: React.ReactNode;
  caveat?: string | null;
}) {
  return (
    <div className="card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{children}</div>
      {caveat ? <div className="stat-caveat">{caveat}</div> : null}
    </div>
  );
}

/** A sample-size-aware metric. Below the significance threshold the number
 *  is shown but visibly demoted -- hiding it would be over-correction, and
 *  showing it plainly would overstate it. */
export function SampledMetric({
  label,
  value,
  sampleSize,
  isSignificant,
  caveat,
  render,
}: {
  label: string;
  value: Maybe;
  sampleSize?: number | null;
  isSignificant?: boolean | null;
  caveat?: string | null;
  render?: (v: number) => React.ReactNode;
}) {
  const known = isKnown(value);
  const weak = known && isSignificant === false;

  return (
    <div className={`card${weak ? " card-weak" : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {known ? (
          render ? (
            render(value)
          ) : (
            <Pct value={value} />
          )
        ) : (
          <Unknown kind={sampleSize === 0 ? "unrecorded" : "insufficient"} />
        )}
      </div>
      <div className="stat-caveat">
        {typeof sampleSize === "number" ? `n = ${sampleSize}` : "sample size not reported"}
        {weak ? " — below the significance threshold; treat as indicative only" : ""}
      </div>
      {caveat ? <div className="stat-caveat">{caveat}</div> : null}
    </div>
  );
}
