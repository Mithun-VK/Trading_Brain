// Every data-backed area of the dashboard has four possible states, and
// collapsing any two of them lies to the reader:
//
//   error    -- we could not ask (API down, 500). We do not know.
//   empty    -- we asked, and the answer is genuinely "nothing yet".
//   success  -- data.
//   loading  -- handled by Next.js `loading.tsx` / <Suspense> boundaries,
//               since these are server components.
//
// The one that gets lost most often is error-vs-empty. "No signals" and
// "we could not reach the signal service" look identical if you render a
// failed fetch as an empty list, and the second one is the dangerous
// reading: it looks like the system had nothing to say when it actually
// had no idea.

import type { ApiResult } from "@/lib/api";

export function ErrorBox({ message, what }: { message: string; what?: string }) {
  return (
    <div className="error-box">
      <strong>Could not load {what ?? "this section"}.</strong>
      <div>{message}</div>
      <div className="error-hint">
        This is a failure to retrieve data — not an indication that there is none.
      </div>
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

/**
 * Render an ApiResult, keeping error and empty visibly distinct.
 *
 * `isEmpty` is passed in rather than inferred: only the caller knows
 * whether an empty array, a zero count, or an `available: false` flag is
 * the "nothing yet" case for that particular endpoint.
 */
export function Loaded<T>({
  result,
  what,
  isEmpty,
  empty,
  children,
}: {
  result: ApiResult<T>;
  what: string;
  isEmpty?: (data: T) => boolean;
  empty?: React.ReactNode;
  children: (data: T) => React.ReactNode;
}) {
  if (!result.ok) return <ErrorBox message={result.error} what={what} />;
  if (isEmpty?.(result.data)) {
    return <EmptyState>{empty ?? `No ${what} recorded yet.`}</EmptyState>;
  }
  return <>{children(result.data)}</>;
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skeleton" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-row" />
      ))}
    </div>
  );
}
