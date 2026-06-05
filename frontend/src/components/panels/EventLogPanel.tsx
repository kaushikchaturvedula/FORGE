import { Empty } from "../Panel";

function timeOnly(iso: string): string {
  const t = String(iso).split("T")[1] || iso;
  return t.replace(/[+Z].*$/, "").slice(0, 8);
}

export function EventLogPanel({ data, events }: { data: any; events: any[] }) {
  // Prefer the panel's own list (full work log) but fall back to streamed log entries.
  const log: any[] = data?.events || events || [];
  const report: string | undefined = data?.report;
  const handoff = data?.handoff;

  if (log.length === 0 && !report && !handoff) {
    return <Empty>Every action is logged here with a timestamp as the job happens.</Empty>;
  }

  return (
    <div className="flex flex-col gap-3">
      {handoff && (
        <div className="rounded border border-forge-accent/40 bg-forge-accent/10 p-2 text-xs">
          <div className="mb-1 font-semibold uppercase tracking-wide text-forge-accent">Shift Handoff (SBAR)</div>
          {(["situation", "background", "assessment", "recommendation"] as const).map((k) => (
            <div key={k} className="mb-1">
              <span className="uppercase text-forge-muted">{k}: </span>
              {Array.isArray(handoff[k]) ? (
                <ul className="ml-3 list-disc text-forge-text">
                  {handoff[k].map((x: string, i: number) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              ) : (
                <span className="text-forge-text">{handoff[k]}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {report && (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-forge-bg p-2 text-[11px] text-forge-text">{report}</pre>
      )}

      <ul className="flex flex-col gap-1 text-sm">
        {[...log].reverse().map((e, i) => (
          <li key={i} className="flex gap-2 border-b border-forge-edge/40 py-1">
            <span className="font-mono text-[11px] text-forge-muted">{timeOnly(e.time)}</span>
            <span className="text-[11px] uppercase text-forge-accent">{e.photo ? "📷" : e.type}</span>
            <span className="flex-1 text-forge-text">{e.note}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
