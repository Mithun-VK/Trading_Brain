import { API_BASE_URL, apiGet } from "@/lib/api";
import type { HealthOut } from "@/lib/types";
import { ErrorBox } from "@/components/ErrorBox";

export default async function SystemPage() {
  const health = await apiGet<HealthOut>("/health");

  return (
    <>
      <h1>System Health</h1>

      <div className="card">
        <div className="stat-label">API base URL</div>
        <div>{API_BASE_URL}</div>
      </div>

      {health.ok ? (
        <div className="card">
          <span className="badge badge-ok">reachable</span>
          <div className="card-grid" style={{ marginTop: "0.6rem" }}>
            <div>
              <div className="stat-label">Status</div>
              <div>{health.data.status}</div>
            </div>
            <div>
              <div className="stat-label">Environment</div>
              <div>{health.data.app_env}</div>
            </div>
          </div>
        </div>
      ) : (
        <>
          <span className="badge badge-warn">unreachable</span>
          <ErrorBox message={health.error} />
        </>
      )}

      <p className="muted" style={{ marginTop: "1rem" }}>
        Interactive API docs (if the API is running):{" "}
        <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noreferrer">
          {API_BASE_URL}/docs
        </a>
      </p>
    </>
  );
}
