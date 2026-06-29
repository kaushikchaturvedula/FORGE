import { Empty } from "../Panel";

export function ProcedurePanel({ data }: { data: any }) {
  if (!data?.mode) return <Empty>Start a procedure or a safety checklist to see steps here.</Empty>;
  const isSafety = data.mode === "safety";
  const items: any[] = isSafety ? data.items || [] : data.steps || [];
  const index = data.index ?? 0;
  // PROCEDURES send an explicit operator-asserted `completed` set; SAFETY has none, so it falls
  // back to sequential positional rendering (i < index).
  const hasCompleted = Array.isArray(data.completed);
  const completed = new Set<number>(data.completed || []);

  if (data.complete) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center">
        <div className="mb-2 text-3xl">✅</div>
        <div className="text-sm font-semibold text-forge-live">{data.title} complete</div>
        {data.message && <div className="mt-1 text-xs text-forge-muted">{data.message}</div>}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-semibold text-forge-text">{data.title}</span>
        <span className="text-xs text-forge-muted">
          step {index + 1} of {items.length}{hasCompleted ? ` · ${completed.size} done` : ""}
        </span>
      </div>

      {isSafety && data.hazard && (
        <div className="mb-2 rounded border-l-2 border-forge-alert bg-forge-alert/10 px-2 py-1 text-xs text-forge-text">
          ⚠ {data.hazard}
        </div>
      )}
      {!isSafety && (data.warnings || []).map((w: string, i: number) => (
        <div key={i} className="mb-1 rounded border-l-2 border-forge-warn bg-forge-warn/10 px-2 py-1 text-xs text-forge-text">
          ⚠ {w}
        </div>
      ))}

      <ol className="flex min-h-0 flex-1 flex-col gap-1 overflow-auto">
        {items.map((step, i) => {
          const current = i === index;
          const done = hasCompleted ? completed.has(i) : i < index;
          return (
            <li
              key={i}
              className={`rounded px-2 py-2 text-sm ${
                current ? "bg-forge-accent/20 ring-1 ring-forge-accent" : done ? "opacity-50" : "bg-forge-bg"
              }`}
            >
              <div className="flex gap-2">
                <span className={`font-mono text-xs ${done ? "text-forge-live" : "text-forge-muted"}`}>
                  {done ? "✓" : step.n ?? i + 1}
                </span>
                <div>
                  <div className="text-forge-text">{step.text}</div>
                  {step.warning && <div className="text-xs text-forge-warn">⚠ {step.warning}</div>}
                  {step.expect && <div className="text-xs text-forge-muted">Expect: {step.expect}</div>}
                  {current && isSafety && (
                    <div className="mt-1 text-xs text-forge-accent">
                      ▸ {step.prompt} — say “confirmed” to advance
                    </div>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
