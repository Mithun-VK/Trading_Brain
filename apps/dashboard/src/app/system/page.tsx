import { API_BASE_URL } from "@/lib/api";
import type { HealthCheck, HealthOut } from "@/lib/types";
import { ErrorBox } from "@/components/Section";

export const dynamic = "force-dynamic";

type HealthFetch = { ok: true; data: HealthOut } | { ok: false; error: string };

/**
 * `/health` answers 503 when the system is unhealthy — and that 503 carries
 * the full check breakdown in its body. The generic `apiGet` treats any
 * non-2xx as an error and keeps only `detail`, which would throw away
 * exactly the diagnosis this page exists to show. So health is fetched
 * directly: an unhealthy answer is data, not a failure. A failure is not
 * being able to ask at all.
 */
async function fetchHealth(path: string): Promise<HealthFetch> {
  const token = process.env.TRADINGBRAIN_API_TOKEN;
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const body = (await response.json()) as HealthOut & { detail?: string };
    if (!body || typeof body.status !== "string") {
      return { ok: false, error: body?.detail ?? `Unexpected response (HTTP ${response.status}).` };
    }
    return { ok: true, data: body };
  } catch (err) {
    return {
      ok: false,
      error: `Could not reach the TradingBrain API at ${API_BASE_URL}. Is it running? (${
        err instanceof Error ? err.message : String(err)
      })`,
    };
  }
}

const STATUS_MEANING: Record<string, string> = {
  healthy: "Working as intended.",
  degraded: "Running with reduced capability or confidence — usable, but read the detail.",
  unavailable: "A required capability is broken.",
};

function CheckRow({ check }: { check: HealthCheck }) {
  return (
    <tr>
      <td>
        <span className={`dot dot-${check.status}`} aria-hidden="true" />{" "}
        <strong>{check.name}</strong>
      </td>
      <td>
        <span className={`badge status-${check.status}`}>{check.status}</span>
      </td>
      <td>{check.detail}</td>
    </tr>
  );
}

function CheckTable({ title, health }: { title: string; health: HealthFetch }) {
  return (
    <>
      <h2>{title}</h2>
      {health.ok ? (
        health.data.checks.length === 0 ? (
          <p className="muted">No checks reported.</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Status</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {health.data.checks.map((c) => (
                  <CheckRow key={c.name} check={c} />
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : (
        <ErrorBox message={health.error} what={title.toLowerCase()} />
      )}
    </>
  );
}

export default async function SystemPage() {
  const [overall, dependencies, data, jobs] = await Promise.all([
    fetchHealth("/health"),
    fetchHealth("/health/dependencies"),
    fetchHealth("/health/data"),
    fetchHealth("/health/jobs"),
  ]);

  return (
    <>
      <h1>System Health</h1>
      <p className="lede">
        A process that is running is not a healthy system. These checks cover dependencies, data
        freshness, and scheduled jobs — the worst status wins, so one broken thing cannot be
        averaged away.
      </p>

      {overall.ok ? (
        <div className={`card health-banner health-${overall.data.status}`}>
          <div className="stat-label">Overall</div>
          <div className="stat-value">{overall.data.status}</div>
          <div className="stat-caveat">{STATUS_MEANING[overall.data.status]}</div>
        </div>
      ) : (
        <ErrorBox message={overall.error} what="system health" />
      )}

      <CheckTable title="Dependencies" health={dependencies} />
      <CheckTable title="Data" health={data} />
      <CheckTable title="Scheduled jobs" health={jobs} />

      <h2>Reference</h2>
      <div className="card">
        <div className="stat-label">API base URL</div>
        <div className="mono">{API_BASE_URL}</div>
        <p className="muted small" style={{ marginTop: "0.5rem" }}>
          Interactive API docs:{" "}
          <a className="link" href={`${API_BASE_URL}/docs`} target="_blank" rel="noreferrer">
            {API_BASE_URL}/docs
          </a>
        </p>
      </div>
    </>
  );
}
