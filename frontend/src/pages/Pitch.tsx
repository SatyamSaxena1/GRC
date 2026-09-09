import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  assignControl,
  createAuditFirm,
  createControl,
  createEngagement,
  createFirmUser,
  createOrganization,
  createUser,
  uploadEvidence,
  type Identity,
} from "../api/client";
import { useSession } from "../lib/session";

const FRAMEWORKS = ["ISO-27001", "PCI-DSS", "SOC-2", "NIST-CSF", "HIPAA", "CIS-CONTROLS", "GDPR"];

const SLIDES = [
  { id: "thesis", label: "Thesis" },
  { id: "problem", label: "Problem" },
  { id: "proof", label: "Proof" },
  { id: "rule", label: "How" },
  { id: "roles", label: "Who" },
  { id: "demo", label: "Live demo" },
  { id: "lifecycle", label: "Lifecycle" },
  { id: "change", label: "Before / after" },
  { id: "numbers", label: "Numbers" },
  { id: "moat", label: "Moat" },
  { id: "start", label: "Start" },
  { id: "glossary", label: "Glossary" },
  { id: "close", label: "Close" },
];

export function PitchPage() {
  const deck = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState("thesis");

  // The document itself is the scroller, so snapping, #anchors and arrow-key
  // paging are all native. A private scroll container would need JS for each,
  // and would silently swallow fragment navigation.
  useEffect(() => {
    document.documentElement.classList.add("deck-mode");
    return () => document.documentElement.classList.remove("deck-mode");
  }, []);

  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && setActive(e.target.id)),
      { threshold: 0.5 }
    );
    deck.current?.querySelectorAll(".slide").forEach((s) => io.observe(s));
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const page = (event: KeyboardEvent) => {
      if (!["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End"].includes(event.key)) return;
      const current = SLIDES.findIndex((slide) => slide.id === active);
      const next = event.key === "Home"
        ? 0
        : event.key === "End"
          ? SLIDES.length - 1
          : Math.max(0, Math.min(SLIDES.length - 1, current + (["ArrowDown", "PageDown"].includes(event.key) ? 1 : -1)));
      event.preventDefault();
      document.getElementById(SLIDES[next].id)?.scrollIntoView();
    };
    window.addEventListener("keydown", page);
    return () => window.removeEventListener("keydown", page);
  }, [active]);

  return (
    <div className="deck" ref={deck}>
      <nav className="deck-rail" aria-label="Slides">
        {SLIDES.map((s) => (
          <a key={s.id} href={`#${s.id}`} className={active === s.id ? "active" : ""}>
            <span>{s.label}</span>
          </a>
        ))}
      </nav>

      <section className="slide slide-hero" id="thesis">
        <div className="slide-inner">
          <span className="deck-eyebrow">GRC evidence platform</span>
          <h1>
            One document.
            <br />
            <em>Every</em> framework.
          </h1>
          <p className="lede">
            Upload an access control policy once. It satisfies ISO 27001 and produces precise,
            actionable PCI DSS gaps in the same pass — automatically, reproducibly, and defensibly
            enough to survive an auditor.
          </p>
          <div className="deck-cta">
            <a className="btn btn-primary" href="#demo">See it running</a>
            <Link className="btn deck-btn-ghost" to="/login">Open the app</Link>
          </div>
          <p className="deck-hint">Scroll, or use ↑ ↓</p>
        </div>
      </section>

      <section className="slide" id="problem">
        <div className="slide-inner">
          <span className="deck-eyebrow">The problem</span>
          <h2>The same policy, uploaded seven times.</h2>
          <div className="deck-split">
            <div>
              <p className="lede">
                Every framework an organisation adds means another evidence request cycle over
                documents it has already handed over. The artefact does not change. Only the clause
                number on the request does.
              </p>
              <p className="lede deck-dim">
                So compliance cost scales with frameworks instead of with risk, and the answer to
                “are we PCI ready?” takes a quarter to produce — long after it could have changed a
                decision.
              </p>
            </div>
            <ul className="deck-stack">
              {FRAMEWORKS.map((f, i) => (
                <li key={f} style={{ marginLeft: `${i * 16}px` }}>
                  <span className="deck-doc">access-control-policy.pdf</span>
                  <span className="deck-tag">{f}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="slide" id="proof">
        <div className="slide-inner">
          <span className="deck-eyebrow">The product in one example</span>
          <h2>One fact. Two framework answers.</h2>
          <div className="deck-proof">
            <div className="deck-proof-source">
              <span>access-control-policy.pdf · page 6</span>
              <strong>“Minimum password length: 8 characters.”</strong>
            </div>
            <div className="deck-proof-results">
              <article className="pass">
                <span>ISO 27001 · A.5.15</span>
                <strong>Evidence linked</strong>
                <p>The policy satisfies this organisation's mapped requirement.</p>
              </article>
              <article className="fail">
                <span>PCI DSS · 8.3.6</span>
                <strong>Gap: 8 observed, 12 required</strong>
                <p>The same sentence becomes a precise remediation task.</p>
              </article>
            </div>
          </div>
          <p className="deck-foot">The evidence is stored once. Each framework is evaluated independently.</p>
        </div>
      </section>

      <section className="slide" id="rule">
        <div className="slide-inner">
          <span className="deck-eyebrow">The architectural rule</span>
          <h2>The model never decides whether a control passes.</h2>
          <div className="deck-cols">
            <article>
              <h3>LLM / VLM</h3>
              <p>
                Extracts facts from the document with page-level provenance. It reports that the
                policy says <em>“8 characters, on page 6.”</em>
              </p>
            </article>
            <article>
              <h3>Python</h3>
              <p>
                Decides compliance deterministically from versioned content packs. 8 &lt; 12, so PCI
                DSS 8.3.6 fails. Same input, same verdict, every run.
              </p>
            </article>
            <article>
              <h3>Human auditor</h3>
              <p>
                Records the verdict that closes and locks the control. After the lock the auditee
                cannot modify it — and the trail is hash-chained.
              </p>
            </article>
          </div>
          <p className="deck-foot">
            That split is what makes a verdict reproducible, injection-resistant, and explainable
            after the fact.
          </p>
        </div>
      </section>

      <section className="slide" id="roles">
        <div className="slide-inner">
          <span className="deck-eyebrow">Who's at the table</span>
          <h2>Five parties, two tenancy axes.</h2>
          <div className="deck-cols deck-cols-5">
            <article>
              <h3>Org admin</h3>
              <p>Runs the auditee's account. Subscribes to frameworks, invites control owners, uploads evidence.</p>
            </article>
            <article>
              <h3>Control owner</h3>
              <p>Sees only the specific controls assigned to them — least privilege, not a filtered view of everything.</p>
            </article>
            <article>
              <h3>Auditor</h3>
              <p>Staffed onto one engagement at a time. Reviews evidence, records the verdict, locks the control.</p>
            </article>
            <article>
              <h3>Firm admin</h3>
              <p>Runs the audit firm's console — approves onboarding requests, staffs auditors onto clients.</p>
            </article>
            <article>
              <h3>Prospect</h3>
              <p>Not a role yet. Requests an audit; a firm's approval is what turns the request into an engagement.</p>
            </article>
          </div>
          <p className="deck-foot">
            Belonging to a firm grants nothing by itself — being staffed on an engagement is the grant.
            Next, watch all four signed-in roles work the same evidence, live.
          </p>
        </div>
      </section>

      <section className="slide slide-demo" id="demo">
        <div className="slide-inner slide-inner-wide">
          <div className="deck-demo-head">
            <div>
              <span className="deck-eyebrow">Live demo</span>
              <h2>Not a screenshot. The product.</h2>
            </div>
            <p className="deck-hint">
              A real tenant against the running backend — then a scripted cursor
              <br />
              walks four different users through their own day.
            </p>
          </div>
          <BrowserFrame />
        </div>
      </section>

      <section className="slide" id="lifecycle">
        <div className="slide-inner">
          <span className="deck-eyebrow">One document's day</span>
          <h2>Upload to lock, in seven steps.</h2>
          <ol className="deck-timeline">
            <li>
              <strong>Upload.</strong>
              <span>An org admin or control owner uploads one artefact, tagged by type — policy, scan report, review record.</span>
            </li>
            <li>
              <strong>Extract.</strong>
              <span>The model reads it and reports facts with page-level provenance — never a verdict, only what the document says and where.</span>
            </li>
            <li>
              <strong>Evaluate.</strong>
              <span>Deterministic Python checks each extracted value against every subscribed framework's content pack, independently.</span>
            </li>
            <li>
              <strong>Link or gap.</strong>
              <span>A satisfied requirement becomes a control link. A shortfall becomes a gap — observed value, required value, the clause that wants it.</span>
            </li>
            <li>
              <strong>Task.</strong>
              <span>Every open gap can raise a remediation task, assigned to the control owner responsible for closing it.</span>
            </li>
            <li>
              <strong>Verdict.</strong>
              <span>An auditor staffed on the engagement reviews the evidence and provenance, then records pass or fail.</span>
            </li>
            <li>
              <strong>Lock.</strong>
              <span>The verdict closes the control. The auditee can no longer modify it, and the change is hash-chained into the audit log.</span>
            </li>
          </ol>
        </div>
      </section>

      <section className="slide" id="change">
        <div className="slide-inner">
          <span className="deck-eyebrow">What changes operationally</span>
          <h2>From repeated evidence hunts to one living evidence record.</h2>
          <div className="deck-before-after">
            <article>
              <span className="deck-compare-label">Before</span>
              <ol>
                <li>Ask for the same document per framework</li>
                <li>Interpret it again in separate spreadsheets</li>
                <li>Describe failures as generic red statuses</li>
                <li>Rebuild the audit trail at review time</li>
              </ol>
            </article>
            <div className="deck-shift" aria-hidden="true">→</div>
            <article className="after">
              <span className="deck-compare-label">With GRC</span>
              <ol>
                <li>Upload once and preserve every version</li>
                <li>Evaluate all subscribed frameworks in one pass</li>
                <li>Turn each shortfall into owned remediation</li>
                <li>Keep provenance, verdicts, and locks together</li>
              </ol>
            </article>
          </div>
        </div>
      </section>

      <section className="slide" id="numbers">
        <div className="slide-inner">
          <span className="deck-eyebrow">The two numbers</span>
          <h2>What reuse is worth.</h2>
          <div className="deck-metrics">
            <div className="deck-metric">
              <strong>86%</strong>
              <span>reuse rate — one artefact satisfied 7 control links, avoiding 6 separate uploads</span>
            </div>
            <div className="deck-metric">
              <strong>40%</strong>
              <span>Day-1 PCI DSS readiness for an ISO-only organisation, before it subscribes</span>
            </div>
            <div className="deck-metric">
              <strong>0</strong>
              <span>invented passes — with the model offline, extraction returns null and every requirement correctly fails</span>
            </div>
          </div>
          <p className="deck-foot mono">GET /analytics/reuse · GET /analytics/readiness/PCI-DSS</p>
        </div>
      </section>

      <section className="slide" id="moat">
        <div className="slide-inner">
          <span className="deck-eyebrow">Why it holds</span>
          <h2>Frameworks are data, not code.</h2>
          <div className="deck-cols">
            <article>
              <h3>A new framework is a YAML file</h3>
              <p>
                Requirements, mappings to the unified control objectives, delta conditions. Seven
                packs ship today; adding the eighth ships no code.
              </p>
            </article>
            <article>
              <h3>Belonging to a firm grants nothing</h3>
              <p>
                Two tenancy axes, and staffing on an engagement is the grant. An unstaffed client
                answers 404 — indistinguishable from one that does not exist.
              </p>
            </article>
            <article>
              <h3>Defensible by construction</h3>
              <p>
                Append-only hash-chained audit log with before/after state, row-level security in
                Postgres, provenance on every extracted attribute.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section className="slide" id="start">
        <div className="slide-inner">
          <span className="deck-eyebrow">A practical first engagement</span>
          <h2>Start with one policy. Prove three things.</h2>
          <div className="deck-start">
            <article>
              <strong>1</strong>
              <div><h3>Can we reuse it?</h3><p>Link one real artefact to every requirement it can support.</p></div>
            </article>
            <article>
              <strong>2</strong>
              <div><h3>Can we trust the answer?</h3><p>Trace each extracted fact to its source and replay each deterministic verdict.</p></div>
            </article>
            <article>
              <strong>3</strong>
              <div><h3>Can we close the gap?</h3><p>Assign the shortfall, upload a corrected version, and lock the auditor's decision.</p></div>
            </article>
          </div>
          <p className="deck-foot">Then add frameworks by loading content packs — without rebuilding the workflow.</p>
        </div>
      </section>

      <section className="slide" id="glossary">
        <div className="slide-inner">
          <span className="deck-eyebrow">In plain terms</span>
          <h2>Six words worth defining.</h2>
          <dl className="deck-glossary">
            <div>
              <dt>Engagement</dt>
              <dd>One audit firm's relationship with one organisation — the unit an auditor gets staffed onto.</dd>
            </div>
            <div>
              <dt>Control</dt>
              <dd>One requirement from one framework, scoped to this organisation — e.g. ISO 27001 A.5.15.</dd>
            </div>
            <div>
              <dt>Evidence</dt>
              <dd>The uploaded artefact itself — a policy, a scan report, a review record — with every version kept.</dd>
            </div>
            <div>
              <dt>Provenance</dt>
              <dd>The page and passage an extracted fact came from, so a verdict can be checked against the source, not the summary.</dd>
            </div>
            <div>
              <dt>Gap</dt>
              <dd>A specific shortfall: the value the evidence showed, the value the clause requires, and nothing vaguer.</dd>
            </div>
            <div>
              <dt>Lock</dt>
              <dd>What an auditor's verdict does to a control — closes it to further edits by the auditee, permanently logged.</dd>
            </div>
          </dl>
          <p className="deck-foot">
            The full list lives in the app itself — <Link to="/glossary">open the glossary</Link>.
          </p>
        </div>
      </section>

      <section className="slide slide-close" id="close">
        <div className="slide-inner">
          <span className="deck-eyebrow">Where it stands</span>
          <h2>The thin slice is end to end.</h2>
          <p className="lede">
            Onboarding, evidence upload, extraction with provenance, deterministic evaluation across
            frameworks, gaps, remediation tasks, auditor verdict, lock. 181 tests, a golden corpus
            with quality gates, and a demo that runs the whole path in one command.
          </p>
          <div className="deck-cta">
            <Link className="btn btn-primary" to="/login">Start a workspace</Link>
            <a className="btn deck-btn-ghost" href="#demo">Back to the demo</a>
          </div>
          <p className="deck-foot mono">python -m demo</p>
        </div>
      </section>
    </div>
  );
}

const ROUTES = [
  { path: "/overview", label: "Overview" },
  { path: "/controls", label: "Controls" },
  { path: "/evidence", label: "Evidence" },
  { path: "/gaps", label: "Gaps" },
  { path: "/tasks", label: "Tasks" },
];

const ORG_NAME = "Acme Corp";
const FIRM_NAME = "Meridian Assurance";

// The golden-corpus document (evaluation/dataset/access_control_policy_v1.txt).
// Uploading this one is what makes the pitch concrete: 8 characters satisfies
// ISO 27001 A.5.15 and fails PCI DSS 8.3.6, from a single artefact.
const POLICY_TEXT = `ASTERON SYSTEMS PVT. LTD. — ACCESS CONTROL POLICY
Document ID: ISP-AC-001 | Version 1.0
Effective Date: 12 March 2026
Approved by: Meera Khanna, Chief Information Security Officer

Document Control
Approval Date: 12 March 2026
Review Frequency: Annual
Next Review Date: 12 March 2027
Status: Approved and Published

6. Authentication and Password Requirements
Minimum password length: 8 characters. Passwords must contain characters from at least three of
the following groups: uppercase letters, lowercase letters, numbers and special characters.

7. Multi-Factor Authentication
Multi-factor authentication (MFA) is mandatory for remote access through the corporate VPN and
for administrative access to cloud management consoles. Standard internal user access from the
managed corporate network may use single-factor authentication.

9. Access Reviews
System Owners shall review user access at least quarterly for critical systems and at least annually
for other in-scope Corporate IT systems.
`;

type Demo = {
  orgId: string;
  engagementId: string;
  ownerId: string;
  firmAdminId: string;
};

type Step = {
  /** The caption shown while this step runs. */
  say: string;
  /** A selector inside the embedded app — the cursor travels to it. */
  at?: string;
  /** Click it for real, rather than just pointing at it. */
  click?: boolean;
  /** How long to dwell once the cursor arrives. */
  hold?: number;
};

type Persona = {
  id: string;
  who: string;
  sub: string;
  home: string;
  identity: (d: Demo) => Identity;
  steps: Step[];
};

// Each script drives the real app as a real identity. Targets are the
// data-tour hooks the in-app tours already rely on, so they stay in step with
// the screens instead of being a second, drifting set of selectors.
const PERSONAS: Persona[] = [
  {
    id: "grc",
    who: "GRC officer",
    sub: `${ORG_NAME} — org admin`,
    home: "/overview",
    identity: (d) => ({ kind: "org", id: d.orgId, label: `${ORG_NAME} (org admin)` }),
    steps: [
      { say: "Morning triage. Controls tracked, open gaps, remediation tasks — the whole day's queue in one row.", at: "[data-tour='stat-cards']" },
      { say: "Evidence reuse: how many control links one artefact is already carrying, and the uploads that never had to happen.", at: "[data-tour='reuse-cards']" },
      { say: "And Day-1 readiness for a framework the organisation has not subscribed to yet.", at: "[data-tour='readiness']" },
      { say: "Evidence lives in one place, not one folder per framework.", at: "[data-tour='nav-evidence']", click: true },
      { say: "Upload the access control policy once. Every subscribed framework evaluates it independently, in the same pass.", at: "[data-tour='upload-form']", hold: 2200 },
      { say: "A gap is never a red X. It is the observed value, the required value, and the clause that wants it.", at: "[data-tour='nav-gaps']", click: true, hold: 2400 },
    ],
  },
  {
    id: "owner",
    who: "Control owner",
    sub: "Priya — assigned controls only",
    home: "/tasks",
    identity: (d) => ({ kind: "user", id: d.ownerId, label: "Priya (control owner)" }),
    steps: [
      { say: "A control owner signs in and sees only the controls assigned to them — least privilege, not a filtered view of everything.", at: ".page-header h2", hold: 2400 },
      { say: "The navigation is shorter too. There is no org-wide screen to open, because there is no org-wide grant.", at: ".sidebar", hold: 2400 },
      { say: "Their queue: the exact gap, the evidence that closes it, and nothing else in the organisation.", at: ".data-table, .empty-state", hold: 2600 },
    ],
  },
  {
    id: "auditor",
    who: "Auditor",
    sub: `${FIRM_NAME} — staffed on this engagement`,
    home: "/controls",
    identity: (d) => ({ kind: "auditor", id: d.engagementId, label: `${FIRM_NAME} (auditor)` }),
    steps: [
      { say: "The same workspace, opened from the other side of the table.", at: ".sidebar .identity-box", hold: 2200 },
      { say: "A review queue scoped to this engagement only. Frameworks outside it are not listed, and other clients answer 404.", at: ".page-header h2", hold: 2400 },
      { say: "Open the evidence to see what the model actually read.", at: "[data-tour='nav-evidence']", click: true },
      { say: "Every extracted value carries the page it came from. The auditor checks the source, not the summary.", at: ".data-table tbody tr", click: true, hold: 1600 },
      { say: "Extracted attributes with provenance — then the verdict that closes and locks the control.", at: "[data-tour='extracted-attributes']", hold: 2600 },
    ],
  },
  {
    id: "firm",
    who: "Firm admin",
    sub: `${FIRM_NAME} — the firm's own console`,
    home: "/firm",
    identity: (d) => ({ kind: "user", id: d.firmAdminId, label: `${FIRM_NAME} (firm admin)` }),
    steps: [
      { say: "The firm's side of the platform: who is asking to be onboarded.", at: "[data-tour='firm-onboarding']", hold: 2400 },
      { say: "And the clients it is engaged by — belonging to the firm grants nothing until an auditor is staffed here.", at: "[data-tour='firm-clients']", hold: 2600 },
    ],
  },
];

const DEMO_KEY = "grc.pitch-demo";

function loadDemo(): Demo | null {
  try {
    return JSON.parse(localStorage.getItem(DEMO_KEY) ?? "null") as Demo | null;
  } catch {
    return null;
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Poll the embedded app until a selector shows up — it is a real SPA loading
 *  real data, so nothing is on screen the instant a route changes. */
async function waitFor(doc: () => Document | null | undefined, sel: string, timeout = 8000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    const el = doc()?.querySelector(sel);
    if (el) return el as HTMLElement;
    await sleep(120);
  }
  return null;
}

/**
 * Browser-in-browser: real chrome around a same-origin iframe of this very SPA.
 * The demo session is created with the same calls the login quick start makes,
 * so nothing here is a mock — the guided walkthroughs move a cursor over the
 * embedded app and click it for real, as whichever identity the persona is.
 */
function BrowserFrame() {
  const { identity, setIdentity } = useSession();
  // Kept across reloads so a presenter who refreshes mid-pitch does not lose
  // the seeded tenant — and with it the persona walkthroughs.
  const [demo, setDemo] = useState<Demo | null>(loadDemo);
  const [src, setSrc] = useState("/overview");
  const [shown, setShown] = useState("/overview");
  const [nonce, setNonce] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number; down: boolean } | null>(null);
  const [caption, setCaption] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);

  const frame = useRef<HTMLIFrameElement>(null);
  const stopped = useRef(false);
  const scale = useRef(1);

  const started = Boolean(demo || identity);

  // The embedded app is rendered at a fixed desktop width and scaled down to
  // whatever the frame is, so the demo always looks like a desktop browser
  // instead of reflowing into a cramped one on a small screen.
  const viewport = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      // A hidden pane/tab reports 0 — keep the last good geometry rather than
      // collapsing the frame and the cursor coordinates that ride on it.
      if (el.clientWidth === 0 || el.clientHeight === 0) return;
      scale.current = Math.min(1, el.clientWidth / 1280);
      el.style.setProperty("--bib-scale", String(scale.current));
      // The logical height is set here rather than as calc(100% / var(--…)):
      // dividing by a substituted var leaves the declaration invalid, and the
      // iframe ends up with no layout height at all.
      el.style.setProperty("--bib-h", `${el.clientHeight / scale.current}px`);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => () => { stopped.current = true; }, []);

  const go = (path: string) => {
    setSrc(path);
    setShown(path);
  };

  const start = async () => {
    setError(null);
    try {
      setBusy("Creating the organisation…");
      const org = await createOrganization(ORG_NAME, FRAMEWORKS);
      const firm = await createAuditFirm(FIRM_NAME);
      const engagement = await createEngagement(firm.id, org.id, FRAMEWORKS);
      setIdentity({ kind: "org", id: org.id, label: `${ORG_NAME} (org admin)` });

      setBusy("Assigning controls…");
      const iso = await createControl(org.id, "ISO-27001", "A.5.15");
      await createControl(org.id, "PCI-DSS", "8.3.6");
      const owner = await createUser("priya@acme.test", org.id, "CONTROL_OWNER");
      await assignControl(iso.id, owner.id);
      const firmAdmin = await createFirmUser("admin@meridian.test", firm.id, "FIRM_ADMIN");

      // Fired, not awaited: the pipeline runs server-side and the evidence
      // screens show its real status while the walkthrough is already moving.
      setBusy("Uploading the access control policy…");
      void uploadEvidence(
        new File([POLICY_TEXT], "access-control-policy.txt", { type: "text/plain" }),
        "POLICY"
      ).catch(() => undefined);

      const seeded = { orgId: org.id, engagementId: engagement.id, ownerId: owner.id, firmAdminId: firmAdmin.id };
      localStorage.setItem(DEMO_KEY, JSON.stringify(seeded));
      setDemo(seeded);
      go("/overview");
      setNonce((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const stop = () => {
    stopped.current = true;
    setPlaying(null);
    setCaption(null);
    setCursor(null);
  };

  const play = async (persona: Persona) => {
    if (!demo) return;
    stopped.current = true;
    await sleep(60);
    stopped.current = false;
    setPlaying(persona.id);
    setIdentity(persona.identity(demo));
    go(persona.home);
    setNonce((n) => n + 1);

    const doc = () => frame.current?.contentDocument;
    const center = (el: HTMLElement) => {
      const win = frame.current?.contentWindow;
      if (!win) return;
      const top = win.scrollY + el.getBoundingClientRect().top - win.innerHeight / 2;
      win.scrollTo({ top: Math.max(0, top) });
    };

    document.getElementById("demo")?.scrollIntoView({ behavior: "smooth" });

    // Wait for the *new* document, not just any: remounting the iframe is a
    // React commit away, so `.app-shell` can still be the previous persona's
    // page — and its stale elements measure as (0, 0).
    const until = Date.now() + 10000;
    while (Date.now() < until) {
      const win = frame.current?.contentWindow;
      if (win?.location.pathname === persona.home && doc()?.querySelector(".app-shell")) break;
      await sleep(120);
    }
    await sleep(600); // let the shell paint before measuring the first target

    for (const step of persona.steps) {
      if (stopped.current) return;
      setCaption(step.say);

      if (step.at) {
        const el = await waitFor(doc, step.at);
        if (el) {
          // Scroll the embedded window itself rather than calling
          // el.scrollIntoView(): that propagates up the frame chain and drags
          // the deck off the demo slide mid-tour.
          center(el);
          await sleep(250);
          let r = el.getBoundingClientRect();
          // First target of a freshly loaded frame can be measured before the
          // embedded app has laid out — that reads as (0, 0). Re-measure once.
          if (r.width === 0 && r.top === 0) {
            await sleep(500);
            center(el);
            r = el.getBoundingClientRect();
          }
          const s = scale.current;
          const h = viewport.current?.clientHeight ?? 0;
          setCursor({
            x: (r.left + Math.min(r.width / 2, 90)) * s,
            y: Math.max(8, Math.min(h - 12, (r.top + Math.min(r.height / 2, 20)) * s)),
            down: false,
          });
          await sleep(850);
          if (stopped.current) return;
          if (step.click) {
            setCursor((c) => (c ? { ...c, down: true } : c));
            await sleep(200);
            el.click();
            setCursor((c) => (c ? { ...c, down: false } : c));
            await sleep(700);
            await waitFor(doc, ".app-shell");
            const path = frame.current?.contentWindow?.location.pathname;
            if (path) setShown(path);
          }
        }
      }

      await sleep(step.hold ?? 1500);
    }

    if (!stopped.current) stop();
  };

  const role = PERSONAS.find((p) => p.id === playing);

  return (
    <div className="bib-wrap">
      {demo && (
        <div className="bib-personas">
          <span className="bib-personas-label">A day in the life of</span>
          {PERSONAS.map((p) => (
            <button
              key={p.id}
              className={playing === p.id ? "active" : ""}
              onClick={() => void play(p)}
            >
              {p.who}
            </button>
          ))}
          {playing && (
            <button className="bib-stop" onClick={stop}>
              Stop
            </button>
          )}
        </div>
      )}

      <div className="bib">
        <div className="bib-chrome">
          <div className="bib-lights">
            <i />
            <i />
            <i />
          </div>
          <div className="bib-tabs">
            <button className="active">
              {role ? `${role.who} · ${role.sub}` : demo ? `${ORG_NAME} — org admin` : "GRC Workspace"}
            </button>
          </div>
        </div>

        <div className="bib-bar">
          <button className="bib-icon" title="Reload" onClick={() => setNonce((n) => n + 1)}>
            ⟳
          </button>
          <div className="bib-url">
            <span className="bib-lock">🔒</span>
            <span className="bib-host">acme.grc.app</span>
            <span className="bib-path">{shown}</span>
          </div>
          <div className="bib-routes">
            {ROUTES.map((r) => (
              <button
                key={r.path}
                className={shown === r.path ? "active" : ""}
                disabled={!started || Boolean(playing)}
                onClick={() => go(r.path)}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        <div className="bib-viewport" ref={viewport}>
          {started ? (
            <iframe ref={frame} key={nonce} src={src} title="GRC workspace live demo" />
          ) : (
            <div className="bib-splash">
              <h3>Start the live demo</h3>
              <p>
                Creates <strong>{ORG_NAME}</strong> as the auditee and <strong>{FIRM_NAME}</strong> as
                the audit firm across all {FRAMEWORKS.length} frameworks, assigns controls, and
                uploads a real access control policy — then walks four different users through it.
              </p>
              {error && <div className="alert alert-error">{error}</div>}
              <button className="btn btn-primary" disabled={Boolean(busy)} onClick={() => void start()}>
                {busy ?? "Start live demo"}
              </button>
              <p className="deck-hint">Needs the backend running — the same one the app talks to.</p>
            </div>
          )}

          {cursor && (
            <div className={`bib-cursor${cursor.down ? " down" : ""}`} style={{ transform: `translate(${cursor.x}px, ${cursor.y}px)` }}>
              <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden>
                <path d="M4 2 L4 20 L9 15.5 L12.2 22 L15.4 20.4 L12.2 14.2 L19 14 Z" fill="#12172b" stroke="#fff" strokeWidth="1.4" strokeLinejoin="round" />
              </svg>
            </div>
          )}

          {caption && (
            <div className="bib-caption">
              {role && <span className="bib-caption-who">{role.who}</span>}
              {caption}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
