import type { ReactNode } from "react";

import { GATES, gateLabel } from "../lib/labels";

const TONES = {
  neutral: "border-slate-300 bg-slate-100 text-slate-800",
  info: "border-sky-300 bg-sky-50 text-sky-900",
  good: "border-emerald-300 bg-emerald-50 text-emerald-900",
  warn: "border-amber-300 bg-amber-50 text-amber-900",
} as const;

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: keyof typeof TONES;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

/** Proxy metrics are always badged, with what they stand in for (PRD §7.2). */
export function ProxyBadge({ proxyFor }: { proxyFor?: string | null }) {
  const text = proxyFor ? `Proxy for ${proxyFor}` : "Proxy metric";
  return (
    <Badge tone="info" title={text}>
      proxy<span className="sr-only">: {text}</span>
    </Badge>
  );
}

export function GateBadge({ gate }: { gate: string }) {
  return <Badge tone={GATES[gate]?.tone ?? "neutral"}>{gateLabel(gate)}</Badge>;
}

export function StaleBadge() {
  return (
    <Badge tone="warn" title="From the transfermarkt-datasets snapshot, which stopped updating">
      stale
    </Badge>
  );
}

export function ValueLabelBadge({ label }: { label: string }) {
  const tone = label === "Undervalued" ? "good" : label === "Premium" ? "warn" : "neutral";
  return <Badge tone={tone}>{label}</Badge>;
}
