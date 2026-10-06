import type { ReactNode } from "react";

export function Card({
  title,
  actions,
  children,
  footer,
  headingLevel = 2,
}: {
  title: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  headingLevel?: 2 | 3;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <Heading className="text-base font-semibold text-slate-900">{title}</Heading>
        {actions}
      </div>
      {children}
      {footer}
    </section>
  );
}
