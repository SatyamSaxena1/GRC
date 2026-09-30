import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { type Identity, loadIdentity, saveIdentity } from "../api/client";
import { applyRoleTheme, roleOf } from "./roles";

type SessionValue = {
  identity: Identity | null;
  setIdentity: (identity: Identity | null) => void;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentityState] = useState<Identity | null>(() => loadIdentity());

  const setIdentity = (next: Identity | null) => {
    saveIdentity(next);
    setIdentityState(next);
  };

  // Whoever you are signed in as, the app wears their colour.
  useEffect(() => applyRoleTheme(roleOf(identity)), [identity]);

  const value = useMemo(() => ({ identity, setIdentity }), [identity]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
