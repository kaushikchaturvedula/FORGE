import { Empty } from "../Panel";

export function MachineDataPanel({ data }: { data: any }) {
  if (!data?.view) return <Empty>Ask for the nameplate, specs, telemetry, history, or a part / torque spec.</Empty>;
  const view = data.view as string;

  if (view === "part") return <Card title={data.part?.name} rows={kv({ "Part #": data.part?.part_number, Spec: data.part?.spec, Assembly: data.part?.assembly })} highlight="part_number" value={data.part?.part_number} />;
  if (view === "torque")
    return (
      <Card
        title={data.torque?.name}
        rows={kv({ Torque: `${data.torque?.torque_nm} Nm`, Sequence: data.torque?.sequence, Size: data.torque?.size, Lube: data.torque?.lubrication })}
        highlight="torque"
        value={`${data.torque?.torque_nm} Nm`}
      />
    );

  if (view === "telemetry") {
    const readings = data.readings || {};
    return (
      <div className="grid grid-cols-2 gap-2">
        {Object.entries(readings).map(([k, v]: [string, any]) => (
          <div key={k} className="rounded bg-forge-bg p-2">
            <div className="text-[10px] uppercase text-forge-muted">{k.replace(/_/g, " ")}</div>
            <div className="font-mono text-lg text-forge-text">
              {v.value} <span className="text-xs text-forge-muted">{v.unit}</span>
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (view === "maintenance" || view === "history") {
    const items = data.maintenance_history || [];
    return (
      <ul className="flex flex-col gap-2 text-sm">
        {items.map((m: any, i: number) => (
          <li key={i} className="rounded bg-forge-bg p-2">
            <div className="flex justify-between text-xs text-forge-muted">
              <span>{m.date}</span>
              <span>{m.work_order}</span>
            </div>
            <div className="text-forge-text">{m.event}</div>
            <div className="text-xs text-forge-muted">{m.notes}</div>
          </li>
        ))}
      </ul>
    );
  }

  if (view === "faults") {
    const faults = data.open_faults || [];
    if (faults.length === 0) return <Empty>No open faults on file.</Empty>;
    return (
      <ul className="flex flex-col gap-2 text-sm">
        {faults.map((f: any, i: number) => (
          <li key={i} className="rounded border-l-2 border-forge-warn bg-forge-bg p-2">
            <div className="flex justify-between text-xs">
              <span className="font-mono text-forge-warn">{f.fault_id}</span>
              <span className="uppercase text-forge-muted">{f.severity}</span>
            </div>
            <div className="text-forge-text">{f.symptom}</div>
            <div className="text-xs text-forge-muted">Suspected: {f.suspected}</div>
          </li>
        ))}
      </ul>
    );
  }

  // nameplate / specs: render the object as nested key/values.
  const omit = new Set(["view", "asset_id"]);
  const entries = Object.entries(data).filter(([k]) => !omit.has(k));
  return <Card title={view.toUpperCase()} rows={entries.map(([k, v]) => ({ k, v: typeof v === "object" ? JSON.stringify(v) : String(v) }))} />;
}

function kv(obj: Record<string, unknown>): { k: string; v: string }[] {
  return Object.entries(obj)
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => ({ k, v: String(v) }));
}

function Card({ title, rows, highlight, value }: { title?: string; rows: { k: string; v: string }[]; highlight?: string; value?: string }) {
  return (
    <div>
      {title && <div className="mb-2 text-sm font-semibold text-forge-text">{title}</div>}
      {highlight && (
        <div className="mb-2 rounded bg-forge-accent/20 px-3 py-2 font-mono text-xl text-forge-text">{value}</div>
      )}
      <dl className="flex flex-col gap-1 text-sm">
        {rows.map((r) => (
          <div key={r.k} className="flex justify-between gap-3 border-b border-forge-edge/50 py-1">
            <dt className="text-forge-muted">{r.k}</dt>
            <dd className="text-right text-forge-text">{r.v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
