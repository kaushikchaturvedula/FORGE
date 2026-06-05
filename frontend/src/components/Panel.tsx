import type { ReactNode } from "react";

export function Panel({ title, accent, children }: { title: string; accent?: string; children: ReactNode }) {
  return (
    <section className="flex min-h-0 flex-col rounded-lg border border-forge-edge bg-forge-panel">
      <header className="flex items-center gap-2 border-b border-forge-edge px-3 py-2">
        <span className="h-2 w-2 rounded-full" style={{ background: accent || "#7d8da3" }} />
        <h2 className="text-xs font-semibold uppercase tracking-wider text-forge-muted">{title}</h2>
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-3">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="flex h-full items-center justify-center text-center text-sm text-forge-muted">{children}</div>;
}
