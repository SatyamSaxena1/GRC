import type { ReactNode } from "react";

/** A hover-revealed explanation. Renders as a plain, absolutely-positioned child —
 * not a wrapper — so it never affects the flex layout of whatever it sits inside
 * (a sidebar nav link, a pill-select button). The parent must be `position: relative`
 * and define where `.hint` pops out via CSS; see index.css. */
export function Hint({ children }: { children: ReactNode }) {
  return (
    <span className="hint" role="tooltip">
      {children}
    </span>
  );
}
