import type { AlertMsg } from "../lib/api";

export function Alerts({ alerts }: { alerts: AlertMsg[] }) {
  if (alerts.length === 0) return null;
  return (
    <div className="pointer-events-none absolute right-4 top-16 z-50 flex w-80 flex-col gap-2">
      {alerts.slice(0, 3).map((a, i) => (
        <div
          key={i}
          className="pointer-events-auto rounded-lg border px-3 py-2 shadow-lg"
          style={{
            background: a.level === "alert" ? "#3b1015" : "#3a2a0c",
            borderColor: a.level === "alert" ? "#ef4444" : "#f59e0b",
          }}
        >
          <div className="flex items-center gap-2">
            <span>{a.level === "alert" ? "🚨" : "⚠️"}</span>
            <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: a.level === "alert" ? "#fca5a5" : "#fcd34d" }}>
              {a.level} {a.channel ? `· ${a.channel.replace(/_/g, " ")}` : ""}
            </span>
          </div>
          <div className="mt-1 text-sm text-forge-text">{a.message}</div>
        </div>
      ))}
    </div>
  );
}
