import { ApiError, createAuditFirm, createEngagement, createFirmUser, createOrganization, requestAs, type Identity } from "../api/client";
import { POLICY_TEXT } from "./demoContent";
import type { DemoWorld } from "./roles";

// One seeded tenant that every demo role signs into, so picking a role is one
// click instead of pasting ids. Built with the same public API calls the old
// Quick start made — stub auth only (AUTH_STUB_ENABLED), never on an SSO deploy.
// Cached per browser, and re-seeded if the backend no longer knows it (fresh DB).

const KEY = "grc.demo-world";
const FRAMEWORKS = ["ISO-27001", "PCI-DSS", "SOC-2", "NIST-CSF", "HIPAA", "CIS-CONTROLS", "GDPR"];
const ORG_NAME = "Acme Corp";
const FIRM_NAME = "Meridian Assurance";

// Controls registered up front so the owner has work and the map has shape.
const CONTROLS: [string, string][] = [
  ["ISO-27001", "A.5.15"], ["ISO-27001", "A.5.18"], ["ISO-27001", "A.5.17"],
  ["PCI-DSS", "8.3.6"], ["PCI-DSS", "8.4.2"], ["SOC-2", "CC6.1"],
];

export function cachedWorld(): DemoWorld | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "null") as DemoWorld | null;
  } catch {
    return null;
  }
}

export function forgetWorld(): void {
  localStorage.removeItem(KEY);
}

/** A cached world is only good if the backend still has it: a fresh database
 *  answers 401/404 for ids it has never seen. */
async function stillThere(w: DemoWorld): Promise<boolean> {
  try {
    await requestAs({ kind: "user", id: w.firmAdminId, label: "" }, "GET", "/firm/engagements");
    await requestAs({ kind: "auditor", id: w.engagementId, label: "" }, "GET", "/controls");
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status >= 400 && err.status < 500) return false;
    throw err; // backend down — say so rather than silently re-seeding
  }
}

export async function ensureWorld(onStep: (msg: string) => void = () => undefined): Promise<DemoWorld> {
  const cached = cachedWorld();
  if (cached) {
    onStep("Checking the demo workspace…");
    if (await stillThere(cached)) return cached;
    forgetWorld();
  }

  onStep("Creating Acme Corp and its audit firm…");
  const org = await createOrganization(ORG_NAME, FRAMEWORKS);
  const firm = await createAuditFirm(FIRM_NAME);
  const engagement = await createEngagement(firm.id, org.id, FRAMEWORKS);
  const asOrg: Identity = { kind: "org", id: org.id, label: "" };

  onStep("Inviting people and registering controls…");
  const owner = await requestAs<{ id: string }>(asOrg, "POST", "/admin/users", {
    json: { email: "priya@acme.test", org_id: org.id, role: "CONTROL_OWNER" },
  });
  const viewer = await requestAs<{ id: string }>(asOrg, "POST", "/admin/users", {
    json: { email: "dev@acme.test", org_id: org.id, role: "COMPLIANCE_VIEWER" },
  });
  const firmAdmin = await createFirmUser("admin@meridian.test", firm.id, "FIRM_ADMIN");
  const controls = await Promise.all(
    CONTROLS.map(([framework, clause]) =>
      requestAs<{ id: string }>(asOrg, "POST", "/admin/controls", { json: { org_id: org.id, framework, clause } })),
  );
  for (const control of controls.slice(0, 3)) {
    await requestAs(asOrg, "POST", "/admin/control-assignments", {
      json: { org_control_id: control.id, user_id: owner.id },
    });
  }

  // Fired, not awaited: the pipeline runs server-side and every screen shows
  // its real progress, so nobody waits on it to sign in.
  onStep("Uploading the access control policy…");
  const form = new FormData();
  form.append("file", new File([POLICY_TEXT], "access-control-policy.txt", { type: "text/plain" }));
  void requestAs(asOrg, "POST", "/evidence?artefact_type=POLICY", { form }).catch(() => undefined);

  const world: DemoWorld = {
    orgId: org.id, firmId: firm.id, engagementId: engagement.id,
    ownerId: owner.id, viewerId: viewer.id, firmAdminId: firmAdmin.id,
    orgName: ORG_NAME, firmName: FIRM_NAME,
  };
  localStorage.setItem(KEY, JSON.stringify(world));
  return world;
}
