import { useEffect, useRef, useState } from "react";
import { Empty } from "../Panel";

interface NavInfo {
  action: string;
  target?: string;
  label?: string;
  center?: { x: number; y: number };
  bbox?: { x: number; y: number; w: number; h: number };
}
interface SchematicData {
  diagram_type?: string;
  title?: string;
  src?: string;
  viewbox?: { w: number; h: number };
  navigate?: NavInfo | null;
}

export function SchematicPanel({ data }: { data: SchematicData }) {
  const vw = data?.viewbox?.w ?? 800;
  const vh = data?.viewbox?.h ?? 600;
  const [viewBox, setViewBox] = useState(`0 0 ${vw} ${vh}`);
  const [highlight, setHighlight] = useState<NavInfo | null>(null);
  const lastNav = useRef("");

  // React to navigation commands.
  useEffect(() => {
    if (!data?.src) return;
    const nav = data.navigate;
    const key = JSON.stringify(nav) + data.src;
    if (key === lastNav.current) return;
    lastNav.current = key;

    if (!nav || nav.action === "reset") {
      setViewBox(`0 0 ${vw} ${vh}`);
      setHighlight(null);
      return;
    }
    if (nav.action === "jump" && nav.bbox && nav.center) {
      // Keep the FULL diagram visible (no zoom) and mark the component with the pulsing
      // highlight rect. Zooming to a sub-region used to crop the baked SVG text into garbled
      // edge fragments ("ly (BT40)", "Coolant union" cut off); showing the whole diagram keeps
      // every label readable while the rect indicates the part.
      setViewBox(`0 0 ${vw} ${vh}`);
      setHighlight(nav);
    } else if (nav.action === "zoom_out") {
      setViewBox(`0 0 ${vw} ${vh}`);
    }
  }, [data, vw, vh]);

  if (!data?.src) {
    return <Empty>Ask to “show the spindle / turret / axes” to load a schematic.</Empty>;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs text-forge-text">{data.title}</span>
        {highlight?.label && <span className="text-xs text-forge-accent">▸ {highlight.label}</span>}
      </div>
      <svg viewBox={viewBox} className="min-h-0 flex-1 transition-all duration-500" preserveAspectRatio="xMidYMid meet">
        <image href={data.src} x={0} y={0} width={vw} height={vh} />
        {highlight?.bbox && (
          <g className="animate-pulseRing">
            <rect
              x={highlight.bbox.x - 6}
              y={highlight.bbox.y - 6}
              width={highlight.bbox.w + 12}
              height={highlight.bbox.h + 12}
              fill="none"
              stroke="#7c3aed"
              strokeWidth={3}
              rx={6}
            />
          </g>
        )}
      </svg>
    </div>
  );
}
