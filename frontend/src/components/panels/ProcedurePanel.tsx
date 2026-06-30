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
  // TO-DO (next-to-perform) vs HIGHLIGHT (the viewed step). Procedures send `current` =
  // completed.length; safety has no goto, so its to-do is just the cursor.
  const todo = typeof data.current === "number" ? data.current : index;

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
          step {todo + 1} of {items.length}{hasCompleted ? ` · ${completed.size} done` : ""}{index !== todo ? ` · viewing ${index + 1}` : ""}
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
          const highlighted = i === index;                       // the viewed step (ring)
          const done = hasCompleted ? completed.has(i) : i < index;
          const isTodo = i === todo && !done;                    // the next-to-perform
          return (
            <li
              key={i}
              className={`rounded px-2 py-2 text-sm ${
                highlighted ? "bg-forge-accent/20 ring-1 ring-forge-accent"
                  : isTodo ? "bg-forge-bg ring-1 ring-forge-live/40"
                  : done ? "opacity-50" : "bg-forge-bg"
              }`}
            >
              <div className="flex gap-2">
                <span className={`font-mono text-xs ${done ? "text-forge-live" : "text-forge-muted"}`}>
                  {done ? "✓" : step.n ?? i + 1}
                </span>
                <div>
                  <div className="text-forge-text">
                    {step.text}
                    {isTodo && index !== todo && <span className="ml-1 text-[10px] uppercase text-forge-live">next</span>}
                  </div>
                  {step.warning && <div className="text-xs text-forge-warn">⚠ {step.warning}</div>}
                  {step.expect && <div className="text-xs text-forge-muted">Expect: {step.expect}</div>}
                  {highlighted && isSafety && (
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
