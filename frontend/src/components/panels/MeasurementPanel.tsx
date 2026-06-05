import { Empty } from "../Panel";

const STATUS_COLOR: Record<string, string> = { ok: "#22c55e", warn: "#f59e0b", alert: "#ef4444" };

export function MeasurementPanel({ data }: { data: any }) {
  const measurements: any[] = data?.measurements || [];
  if (measurements.length === 0) return <Empty>Recorded readings (torque, temp, speed, wear) appear here with threshold checks.</Empty>;

  return (
    <ul className="flex flex-col gap-1 text-sm">
      {[...measurements].reverse().map((m, i) => (
        <li
          key={i}
          className="flex items-center justify-between rounded px-2 py-2"
          style={{ background: m.status === "ok" ? "#0f1620" : `${STATUS_COLOR[m.status]}1a`, borderLeft: `3px solid ${STATUS_COLOR[m.status] || "#7d8da3"}` }}
        >
          <div>
            <div className="text-[10px] uppercase text-forge-muted">{String(m.type).replace(/_/g, " ")}</div>
            <div className="font-mono text-lg text-forge-text">
              {m.value} <span className="text-xs text-forge-muted">{m.unit}</span>
            </div>
          </div>
          <div className="text-right">
            <span className="text-xs font-semibold uppercase" style={{ color: STATUS_COLOR[m.status] }}>
              {m.status}
            </span>
            {(m.breaches || []).slice(0, 1).map((b: any, j: number) => (
              <div key={j} className="max-w-[10rem] text-[10px] text-forge-muted">
                {b.channel} ≥ {b.limit}
              </div>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}
