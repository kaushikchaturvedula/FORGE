import type { AlertMsg } from "../lib/api";

const TONE: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  alert: { bg: "#3b1015", border: "#ef4444", text: "#fca5a5", icon: "🚨" },
  warn: { bg: "#3a2a0c", border: "#f59e0b", text: "#fcd34d", icon: "⚠️" },
  success: { bg: "#1b4332", border: "#22c55e", text: "#86efac", icon: "✅" },
};

export function Alerts({ alerts, onDismiss }: { alerts: AlertMsg[]; onDismiss?: (i: number) => void }) {
  if (alerts.length === 0) return null;
  return (
    <div className="pointer-events-none absolute right-4 top-16 z-50 flex w-80 flex-col gap-2">
      {alerts.slice(0, 3).map((a, i) => {
        const t = TONE[a.level] || TONE.warn;
        return (
        <div
          key={i}
          className="pointer-events-auto rounded-lg border px-3 py-2 shadow-lg"
          style={{ background: t.bg, borderColor: t.border }}
        >
          <div className="flex items-center gap-2">
            <span>{t.icon}</span>
            <span className="flex-1 text-xs font-semibold uppercase tracking-wide" style={{ color: t.text }}>
              {a.level} {a.channel ? `· ${a.channel.replace(/_/g, " ")}` : ""}
            </span>
            {onDismiss && (
              <button onClick={() => onDismiss(i)} className="text-forge-muted hover:text-forge-text" aria-label="Dismiss alert">
                ✕
              </button>
            )}
          </div>
          <div className="mt-1 text-sm text-forge-text">{a.message}</div>
        </div>
        );
      })}
    </div>
  );
}
