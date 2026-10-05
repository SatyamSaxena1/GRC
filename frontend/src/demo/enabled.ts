import { useSyncExternalStore } from "react";

// Demo tools are opt-in: real customers never see a sample library. A presenter
// turns them on with ?demo=1, Alt+G, or the toggle on the login screen.
const KEY = "grc:demo-guide:on";
const EVENT = "grc:demo-toggle";
export const OPEN_EVENT = "grc:demo-open";

const read = (): boolean => {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
};

export function setDemoEnabled(on: boolean): void {
  try {
    if (on) localStorage.setItem(KEY, "1");
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: the toggle simply does not persist */
  }
  window.dispatchEvent(new Event(EVENT));
}

const subscribe = (cb: () => void) => {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
};

export const useDemoEnabled = (): boolean => useSyncExternalStore(subscribe, read, () => false);
export const openDemoPanel = (): void => {
  setDemoEnabled(true);
  window.dispatchEvent(new Event(OPEN_EVENT));
};
