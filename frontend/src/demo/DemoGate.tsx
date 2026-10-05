import { lazy, Suspense, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation } from "react-router-dom";
import { OPEN_EVENT, setDemoEnabled, useDemoEnabled } from "./enabled";

// Everything heavy (the sample library, later the guide) arrives on demand; this
// file is all that ships in the main bundle.
const DemoPanel = lazy(() => import("./DemoPanel"));

/** Mounted once, as a sibling of <Routes>, so it survives navigation and also
 *  shows on /login. Renders nothing unless demo tools were switched on. */
export function DemoGate() {
  const enabled = useDemoEnabled();
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  // ?demo=1 switches the tools on (and ?demo=0 off) - the link a presenter bookmarks.
  useEffect(() => {
    const flag = new URLSearchParams(window.location.search).get("demo");
    if (flag === "1") setDemoEnabled(true);
    if (flag === "0") setDemoEnabled(false);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Alt+G: digits and Alt+1-5 are already taken (role deck / role switcher).
      if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === "KeyG") {
        e.preventDefault();
        setDemoEnabled(!enabled);
        if (enabled) setOpen(false);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onOpen);
    };
  }, [enabled]);

  // The pitch page embeds this whole app in an iframe; a second pill in there
  // would be noise, and /pitch has its own scripted demo.
  const embedded = window.self !== window.top;
  if (!enabled || embedded || pathname.startsWith("/pitch")) return null;

  return createPortal(
    <>
      <div className="demo-pill" role="group" aria-label="Demo tools">
        <button type="button" className="demo-pill__main" onClick={() => setOpen(true)}>
          Demo documents
        </button>
        <button type="button" className="demo-pill__off" aria-label="Turn demo tools off"
                onClick={() => { setOpen(false); setDemoEnabled(false); }}>×</button>
      </div>
      {open && (
        <Suspense fallback={null}>
          <DemoPanel onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>,
    document.body,
  );
}
