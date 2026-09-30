import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { cachedWorld } from "../lib/demoWorld";
import { reachOf } from "../lib/nav";
import { ROLES, roleOf, type RoleDef } from "../lib/roles";
import { useSession } from "../lib/session";

/**
 * Five swatches at the top of the sidebar: click one (or press Alt+1…5) and you
 * are that person, on the same screen if they can see it, otherwise on their
 * home. Only present once the demo tenant exists — a session signed in by hand
 * or via SSO has no one else to become.
 */
export function RoleSwitcher() {
  const { identity, setIdentity } = useSession();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const world = cachedWorld();
  const current = roleOf(identity);

  const become = (role: RoleDef) => {
    if (!world || role.id === current?.id) return;
    const next = role.identity(world);
    setIdentity(next);
    // Staying put is what makes the switch a comparison: the same screen,
    // seen by someone else. Detail pages (/controls/:id) stay too when the
    // new role has their list.
    const base = "/" + pathname.split("/")[1];
    const keep = reachOf(next).has(pathname) || reachOf(next).has(base);
    navigate(keep ? pathname : role.home, { replace: true });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey) return;
      const role = ROLES.find((r) => `Digit${r.key}` === e.code);
      if (role) {
        e.preventDefault();
        become(role);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!world) {
    return current ? (
      <div className="role-switch role-switch--solo" style={{ "--c": current.color } as React.CSSProperties}>
        <span className="role-switch__chip" />
        <span className="role-switch__name">{current.name}</span>
      </div>
    ) : null;
  }

  return (
    <div className="role-switch" role="radiogroup" aria-label="Switch role">
      <span className="role-switch__label">Viewing as · Alt+1–5</span>
      {ROLES.map((role) => (
        <button
          key={role.id}
          type="button"
          role="radio"
          aria-checked={role.id === current?.id}
          className={role.id === current?.id ? "is-current" : ""}
          style={{ "--c": role.color } as React.CSSProperties}
          title={`${role.name} (${role.swatch}) — Alt+${role.key}`}
          onClick={() => become(role)}
        >
          <span className="role-switch__chip" />
          <span className="role-switch__name">{role.name}</span>
        </button>
      ))}
    </div>
  );
}
