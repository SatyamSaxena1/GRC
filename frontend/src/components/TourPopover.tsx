import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

type Placement = "top" | "bottom" | "left" | "right";
const GAP = 12;            // px between the target and the card
const MARGIN = 12;         // px min distance from any viewport edge
const CARD_W = 320;

/** One guided-tour step, anchored beside a real element on the page. No overlay,
 * no page dimming, no spotlight cutout — the page stays fully visible and
 * clickable behind it. The only mark on the target is a thin ring so you can
 * see what the step is pointing at. Portaled to <body> so its fixed position
 * ranks in the root stacking context (see the deleted .tour-coachmark saga). */
export function TourPopover({
  targetSelector,
  step,
  total,
  title,
  body,
  hint,
  nextLabel,
  onBack,
  onNext,
  onClose,
}: {
  targetSelector: string;
  step: number;          // 0-based
  total: number;
  title: string;
  body: string;
  hint?: string;         // e.g. the "click this" instruction for a walk-across tour
  nextLabel?: string;
  onBack: () => void;
  onNext: () => void;
  onClose: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; placement: Placement } | null>(null);

  useLayoutEffect(() => {
    const target = document.querySelector(targetSelector);
    if (!(target instanceof HTMLElement)) {
      setPos(null);
      return;
    }
    target.classList.add("tour-ring");
    target.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    cardRef.current?.focus();

    const place = () => {
      const t = target.getBoundingClientRect();
      const card = cardRef.current?.getBoundingClientRect();
      const h = card?.height ?? 160;
      const w = card?.width ?? CARD_W;
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      // First placement with room wins; order = below, above, right, left.
      let placement: Placement = "bottom";
      if (t.bottom + GAP + h <= vh - MARGIN) placement = "bottom";
      else if (t.top - GAP - h >= MARGIN) placement = "top";
      else if (t.right + GAP + w <= vw - MARGIN) placement = "right";
      else placement = "left";

      let top: number;
      let left: number;
      if (placement === "bottom" || placement === "top") {
        left = t.left + t.width / 2 - w / 2;
        top = placement === "bottom" ? t.bottom + GAP : t.top - GAP - h;
      } else {
        top = t.top + t.height / 2 - h / 2;
        left = placement === "right" ? t.right + GAP : t.left - GAP - w;
      }
      top = Math.max(MARGIN, Math.min(top, vh - h - MARGIN));
      left = Math.max(MARGIN, Math.min(left, vw - w - MARGIN));
      setPos({ top, left, placement });
    };

    place();
    // Re-anchor while the smooth scroll settles, and on any later scroll/resize.
    const settle = window.setTimeout(place, 350);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.clearTimeout(settle);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      target.classList.remove("tour-ring");
    };
  }, [targetSelector]);

  const last = step === total - 1;

  return createPortal(
    <div
      ref={cardRef}
      className="tour-pop"
      data-placement={pos?.placement ?? "bottom"}
      role="dialog"
      aria-modal="false"
      aria-labelledby="tour-pop-title"
      tabIndex={-1}
      style={pos ? { top: pos.top, left: pos.left } : { top: MARGIN, left: MARGIN, visibility: "hidden" }}
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      <div className="tour-pop__bar" aria-label={`Step ${step + 1} of ${total}`}>
        {Array.from({ length: total }, (_, i) => (
          <span key={i} className={i <= step ? "on" : ""} />
        ))}
      </div>
      <button className="tour-pop__x" onClick={onClose} aria-label="Close tour">×</button>
      <p className="tour-pop__eyebrow">{step + 1} / {total}</p>
      <h3 id="tour-pop-title">{title}</h3>
      <p className="tour-pop__body">{body}</p>
      {hint && <p className="tour-pop__hint">{hint}</p>}
      <div className="tour-pop__nav">
        <button className="btn" disabled={step === 0} onClick={onBack}>Back</button>
        <button className="btn btn-primary" onClick={onNext}>
          {last ? "Done" : (nextLabel ?? "Next")}
        </button>
      </div>
    </div>,
    document.body,
  ) as ReactNode;
}
