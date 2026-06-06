import { useEffect, useRef, useState } from "react";

// The whole-machine schematic. It's the precise highlight surface (the bundled GLB is a
// fused mesh, so part-highlighting lives here). The SVG renders INLINE so its cmp-<name>
// groups are DOM-addressable; FORGE pointing at a part = toggling `is-highlighted` on a
// group. Highlights arrive as a bumped `highlight.seq` and auto-clear after a few seconds.
export interface Highlight {
  component: string;
  svg_id: string;
  label: string;
  seq: number;
}

const SVG_URL = "/schematics/cnc_turnmill_overview.svg";
const CLEAR_MS = 6500;

export function OverviewPanel({ highlight }: { highlight: Highlight | null }) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const lastSeq = useRef(0);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    fetch(SVG_URL)
      .then((r) => r.text())
      .then((t) => alive && setSvg(t))
      .catch(() => alive && setSvg(null));
    return () => {
      alive = false;
    };
  }, []);

  function clearAll() {
    hostRef.current?.querySelectorAll(".is-highlighted").forEach((el) => el.classList.remove("is-highlighted"));
  }

  useEffect(() => {
    if (!svg || !highlight || highlight.seq === lastSeq.current) return;
    lastSeq.current = highlight.seq;
    const host = hostRef.current;
    if (!host) return;
    clearAll();
    const el = host.querySelector(`#${CSS.escape(highlight.svg_id)}`);
    if (el) {
      el.classList.add("is-highlighted");
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(clearAll, CLEAR_MS);
    }
    return () => window.clearTimeout(timer.current);
  }, [svg, highlight]);

  return (
    <div className="flex h-full min-h-[280px] flex-col">
      {svg ? (
        // The SVG is a trusted, bundled static asset (no user content).
        <div ref={hostRef} className="min-h-0 flex-1 [&_svg]:h-full [&_svg]:w-full" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-forge-muted">Loading schematic…</div>
      )}
      <div className="mt-1 h-5 text-center text-xs text-forge-vision">{highlight ? `▸ ${highlight.label}` : ""}</div>
    </div>
  );
}
