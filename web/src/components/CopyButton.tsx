import { useState } from "react";

/** Copy text to the clipboard with a visible, announced confirmation. */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={() => {
          navigator.clipboard.writeText(text).then(
            () => {
              setState("copied");
            },
            () => {
              setState("failed");
            },
          );
        }}
        className="rounded-md border border-slate-300 bg-white px-3 py-1 text-sm text-slate-800 hover:bg-slate-50 focus:ring-2 focus:ring-accent-600 focus:outline-none"
      >
        {label}
      </button>
      <span role="status" className="text-xs text-slate-600">
        {state === "copied" ? "Copied." : state === "failed" ? "Copy failed; select the text." : ""}
      </span>
    </span>
  );
}
