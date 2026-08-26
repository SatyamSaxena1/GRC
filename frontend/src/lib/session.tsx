import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { type Identity, loadIdentity, saveIdentity } from "../api/client";

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

  const value = useMemo(() => ({ identity, setIdentity }), [identity]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
