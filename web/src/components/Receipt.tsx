import { formatDate } from "../lib/format";
import { sourceLabel } from "../lib/labels";

export interface ReceiptItem {
  source: string;
  asOf: string | null | undefined;
}

/** "Source · as of" footer: every number on a card can be traced (PRD §13). */
export function Receipt({ items }: { items: ReceiptItem[] }) {
  const newest = new Map<string, string | null | undefined>();
  for (const { source, asOf } of items) {
    const old = newest.get(source);
    if (old === undefined || (asOf != null && (old == null || asOf > old))) {
      newest.set(source, asOf);
    }
  }
  if (newest.size === 0) {
    return null;
  }
  return (
    <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-600">
      {[...newest.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([source, asOf]) => `${sourceLabel(source)} · as of ${formatDate(asOf)}`)
        .join("  |  ")}
    </p>
  );
}
