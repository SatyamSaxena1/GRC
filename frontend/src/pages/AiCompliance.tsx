import { Link } from "react-router-dom";
import {
  getControl,
  getDashboard,
  listControls,
  listEvidence,
  listGaps,
  type ControlDetail,
  type GapRow,
} from "../api/client";
import { useApi } from "../lib/useApi";

const FRAMEWORK = "NIST-AI-RMF";
const VERDICT_RANK: Record<string, number> = { PASS: 3, PARTIAL: 2, FAIL: 1, NO_EVIDENCE: 0 };

const DOMAINS = [
  {
    label: "Governance foundations",
    description: "Policies, risk tolerance and review cadence",
    clauses: ["GOVERN 1.1", "GOVERN 1.2", "GOVERN 1.3", "GOVERN 1.5"],
    icon: "building",
  },
  {
    label: "Inventory & lifecycle",
    description: "Know every AI system and retire it safely",
    clauses: ["GOVERN 1.6", "GOVERN 1.7"],
    icon: "grid",
  },
  {
    label: "People & oversight",
    description: "Clear ownership, training and human control",
    clauses: ["GOVERN 2.1", "GOVERN 2.2", "GOVERN 3.2"],
    icon: "people",
  },
  {
    label: "Ecosystem resilience",
    description: "Incidents and third-party AI risk",
    clauses: ["GOVERN 4.3", "GOVERN 6.1"],
    icon: "shield",
  },
] as const;

const GAI_RISKS = [
  "CBRN capabilities", "Confabulation", "Dangerous content", "Data privacy",
  "Environmental impact", "Harmful bias", "Human–AI configuration", "Information integrity",
  "Information security", "Intellectual property", "Abusive content", "Value-chain integration",
];

const USE_CASES = [
  { sector: "Government", title: "City of San José", note: "A four-level maturity review across all RMF functions.", href: "https://airc.nist.gov/docs/City_of_San_Jose_CA.pdf" },
  { sector: "Government", title: "Inclusive AI hiring", note: "PEAT’s disability-centered profile for employers and job seekers.", href: "https://www.peatworks.org/AI_Framework/PEAT_AI_and_Inclusive_Hiring_Framework_v24-Sept-2024-ODT.odt" },
  { sector: "Industry", title: "Workday", note: "Common controls, an advisory board and third-party questionnaires.", href: "https://airc.nist.gov/docs/workday-success-story.pdf" },
  { sector: "Industry", title: "Google DeepMind", note: "A practical gap-analysis workbook organized by RMF function.", href: "https://airc.nist.gov/docs/Template_Google_DeepMind_gap_analysis-NIST_AIRMF_1.0.xlsx" },
  { sector: "Industry", title: "Financial services", note: "Sector-specific adoption stages and control objectives from CRI.", href: "https://cyberriskinstitute.org/artificial-intelligence-risk-management/" },
  { sector: "Academia", title: "Autonomous vehicles", note: "A full lifecycle profile for traffic-sign recognition systems.", href: "https://airc.nist.gov/docs/Traffic_Sign_Recognition_Use_Case_Profile-NIST_AI_RMF.pdf" },
];

const TECHNICAL_GUIDES = [
  { code: "NIST AI 600-1", title: "Generative AI profile", note: "GAI-specific risks and actions mapped back to the AI RMF.", href: "https://doi.org/10.6028/NIST.AI.600-1" },
  { code: "NIST AI 100-4", title: "Synthetic content", note: "Detection, authentication, watermarking and provenance metadata.", href: "https://doi.org/10.6028/NIST.AI.100-4" },
  { code: "NIST AI 700 series", title: "Evaluation in practice", note: "GenAI pilot testing and ARIA’s human-centered impact evaluation.", href: "https://airc.nist.gov/technical-reports/" },
  { code: "SP 800-218A · AI 100-2", title: "Secure AI engineering", note: "AI model development practices and adversarial ML terminology.", href: "https://airc.nist.gov/technical-reports/" },
  { code: "SP 1270 · NISTIR 8312/8367", title: "Bias & explainability", note: "Socio-technical bias, explainability principles and interpretation.", href: "https://airc.nist.gov/technical-reports/" },
  { code: "NIST AI 100-3 · 100-5", title: "Language & standards", note: "A shared trustworthy-AI vocabulary and standards engagement plan.", href: "https://airc.nist.gov/technical-reports/" },
];

const CROSSWALKS = ["ISO/IEC 42001", "ISO/IEC 23894", "ISO/IEC 42005", "Singapore AI Verify", "Japan AI Guidelines", "OECD · EU · US principles"];

function Icon({ name }: { name: string }) {
  const paths: Record<string, JSX.Element> = {
    building: <><path d="M4 21V5l8-3 8 3v16" /><path d="M9 21v-4h6v4M8 8h.01M12 8h.01M16 8h.01M8 12h.01M12 12h.01M16 12h.01" /></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    people: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
    shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function bestVerdict(control: ControlDetail) {
  if (!control.links.length) return "NO_EVIDENCE";
  return control.links.reduce((best, link) =>
    (VERDICT_RANK[link.verdict] ?? 0) > (VERDICT_RANK[best] ?? -1) ? link.verdict : best,
  control.links[0].verdict);
}

function PriorityList({ gaps, hasPolicy, hasInventory, subscribed }: {
  gaps: GapRow[];
  hasPolicy: boolean;
  hasInventory: boolean;
  subscribed: boolean;
}) {
  if (gaps.length) {
    return (
      <div className="ai-task-list">
        {gaps.slice(0, 3).map((gap) => (
          <Link className="ai-task" to={`/evidence/${gap.evidence_id}`} key={gap.id}>
            <span className="ai-task-mark">!</span>
            <span><strong>{gap.clause}</strong><small>{gap.required_action}</small></span>
            <span aria-hidden="true">→</span>
          </Link>
        ))}
      </div>
    );
  }

  const starters = [
    !subscribed && ["Register AI RMF controls", "Add the required NIST AI RMF clauses from Admin.", "/admin"],
    !hasPolicy && ["Upload an AI policy", "Document roles, oversight and risk tolerance.", "/evidence"],
    !hasInventory && ["Create an AI inventory", "Record owners, risk tiers and lifecycle status.", "/evidence"],
  ].filter(Boolean) as string[][];

  return starters.length ? (
    <div className="ai-task-list">
      {starters.map(([title, body, to], index) => (
        <Link className="ai-task" to={to} key={title}>
          <span className="ai-task-mark">{index + 1}</span>
          <span><strong>{title}</strong><small>{body}</small></span>
          <span aria-hidden="true">→</span>
        </Link>
      ))}
    </div>
  ) : <div className="ai-clear-state"><Icon name="shield" /><strong>No open AI governance gaps</strong><span>Your current evidence satisfies every active AI control.</span></div>;
}

export function AiCompliancePage() {
  const overview = useApi(async () => {
    const [dashboard, summaries, gaps, policies, inventories] = await Promise.all([
      getDashboard(),
      listControls(),
      listGaps("OPEN"),
      listEvidence({ artefact_type: "AI_POLICY", lifecycle_status: "CURRENT" }),
      listEvidence({ artefact_type: "AI_INVENTORY", lifecycle_status: "CURRENT" }),
    ]);
    const aiControls = summaries.filter((control) => control.framework === FRAMEWORK);
    return {
      dashboard,
      gaps: gaps.filter((gap) => gap.framework === FRAMEWORK),
      policies,
      inventories,
      controls: await Promise.all(aiControls.map((control) => getControl(control.id))),
    };
  }, []);

  const data = overview.data;
  const readiness = data?.dashboard.readiness.find((item) => item.framework === FRAMEWORK);
  const total = readiness?.total_requirements ?? 11;
  const satisfied = readiness?.satisfied ?? 0;
  const score = readiness ? Math.round(readiness.readiness * 100) : 0;
  const assessed = data?.controls.filter((control) => control.links.length > 0).length ?? 0;
  const passed = new Set(data?.controls.filter((control) => bestVerdict(control) === "PASS").map((control) => control.clause));
  const subscribed = readiness?.already_subscribed ?? false;
  const evidenceCount = (data?.policies.length ?? 0) + (data?.inventories.length ?? 0);

  return (
    <div className="ai-compliance">
      <section className="ai-hero">
        <div>
          <span className="ai-kicker"><span /> AI governance workspace</span>
          <h2>Build AI people can trust.</h2>
          <p>
            Turn the NIST AI Risk Management Framework into clear evidence, accountable owners,
            and a defensible record of how AI risk is governed.
          </p>
          <div className="ai-actions">
            <Link className="btn ai-btn-primary" to="/evidence">Add AI evidence <span aria-hidden="true">→</span></Link>
            <a className="btn ai-btn-quiet" href="https://airc.nist.gov/" target="_blank" rel="noreferrer">Explore NIST AIRC ↗</a>
          </div>
        </div>
        <div className="ai-score-card" aria-label={`${score}% AI RMF readiness`}>
          <div className="ai-score" style={{ background: `conic-gradient(#49a97a ${score * 3.6}deg, rgba(255,255,255,.13) 0deg)` }}>
            <div><strong>{score}%</strong><span>ready</span></div>
          </div>
          <div>
            <span className={`ai-status ${subscribed ? "is-live" : ""}`}>{subscribed ? "Active" : "Preview"}</span>
            <strong>NIST AI RMF 1.0</strong>
            <small>{satisfied} of {total} outcomes evidenced</small>
          </div>
        </div>
      </section>

      <nav className="ai-page-nav" aria-label="AI compliance sections">
        <a href="#posture">Posture</a><a href="#genai">GenAI profile</a><a href="#patterns">Implementation patterns</a><a href="#library">Reference library</a>
      </nav>

      {overview.error && <div className="alert alert-error">{overview.error}</div>}

      <section className="ai-kpis" id="posture" aria-label="AI compliance summary">
        <div className="ai-kpi"><span>Framework</span><strong>NIST AI RMF</strong><small>Voluntary · outcome-based</small></div>
        <div className="ai-kpi"><span>Controls assessed</span><strong>{assessed}<em> / {total}</em></strong><small>{subscribed ? "Across active AI requirements" : "Preview before activation"}</small></div>
        <div className="ai-kpi"><span>Open gaps</span><strong>{data?.gaps.length ?? "—"}</strong><small>{data?.gaps.length ? "Require an evidence update" : "No active findings"}</small></div>
        <div className="ai-kpi"><span>AI evidence</span><strong>{evidenceCount}</strong><small>Policies and inventories</small></div>
      </section>

      <section className="ai-function-strip" aria-label="NIST AI RMF functions">
        {[
          ["01", "Govern", "Active evidence checks"],
          ["02", "Map", "Context and impact"],
          ["03", "Measure", "Analysis and testing"],
          ["04", "Manage", "Prioritize and respond"],
        ].map(([number, label, detail], index) => (
          <div className={index === 0 ? "active" : ""} key={label}>
            <span>{number}</span><strong>{label}</strong><small>{detail}</small>
          </div>
        ))}
      </section>

      <div className="ai-content-grid">
        <section className="ai-panel">
          <div className="ai-panel-header">
            <div><span className="ai-section-label">Current scope</span><h3>Governance foundations</h3></div>
            <span className="ai-framework-chip">11 document-verifiable outcomes</span>
          </div>
          <p className="ai-panel-intro">
            Focused on the GOVERN outcomes that can be proven with policy, inventory, training,
            review and incident records. Each finding points to the exact missing statement.
          </p>
          <div className="ai-domain-list">
            {DOMAINS.map((domain) => {
              const complete = domain.clauses.filter((clause) => passed.has(clause)).length;
              const progress = Math.round((complete / domain.clauses.length) * 100);
              return (
                <div className="ai-domain-row" key={domain.label}>
                  <span className="ai-domain-icon"><Icon name={domain.icon} /></span>
                  <span className="ai-domain-copy"><strong>{domain.label}</strong><small>{domain.description}</small></span>
                  <span className="ai-domain-progress"><span><i style={{ width: `${progress}%` }} /></span><small>{complete}/{domain.clauses.length}</small></span>
                </div>
              );
            })}
          </div>
          <Link className="ai-text-link" to="/controls">Open the control register <span aria-hidden="true">→</span></Link>
        </section>

        <aside className="ai-side-stack">
          <section className="ai-panel ai-priority-panel">
            <div className="ai-panel-header">
              <div><span className="ai-section-label">Next best action</span><h3>{data?.gaps.length ? "Priority findings" : "Start your program"}</h3></div>
              {data?.gaps.length ? <span className="ai-count">{data.gaps.length}</span> : null}
            </div>
            <PriorityList gaps={data?.gaps ?? []} hasPolicy={Boolean(data?.policies.length)} hasInventory={Boolean(data?.inventories.length)} subscribed={subscribed} />
            {Boolean(data?.gaps.length) && <Link className="ai-text-link" to="/gaps">Open the gap register <span aria-hidden="true">→</span></Link>}
          </section>

          <section className="ai-resource-card">
            <span className="ai-section-label">Reference library</span>
            <h3>Grounded in NIST guidance</h3>
            <p>The AI RMF is voluntary and use-case agnostic. Tailor it to your risk tolerance instead of treating every suggestion as a checklist.</p>
            <a href="https://doi.org/10.6028/NIST.AI.100-1" target="_blank" rel="noreferrer">Download the framework <span aria-hidden="true">↗</span></a>
            <a href="https://airc.nist.gov/docs/AI_RMF_Playbook.pdf" target="_blank" rel="noreferrer">Explore the Playbook <span aria-hidden="true">↗</span></a>
            <small>Revision watch · NIST is currently updating AI RMF 1.0.</small>
          </section>
        </aside>
      </div>

      <section className="ai-research-section" id="genai">
        <div className="ai-research-heading">
          <div><span className="ai-section-label">Profile lens</span><h3>Go beyond general-purpose governance</h3></div>
          <p>Profiles adapt the RMF to a technology, sector or use case. Start with the context of the system, then select the risks and actions that actually apply.</p>
        </div>
        <div className="ai-profile-grid">
          <article className="ai-genai-card">
            <div className="ai-card-topline"><span>Generative AI</span><span>NIST AI 600-1</span></div>
            <h4>Screen for risks unique to—or intensified by—generative models.</h4>
            <div className="ai-risk-cloud">
              {GAI_RISKS.map((risk) => <span key={risk}>{risk}</span>)}
            </div>
            <a href="https://doi.org/10.6028/NIST.AI.600-1" target="_blank" rel="noreferrer">View the Generative AI Profile <span aria-hidden="true">↗</span></a>
          </article>
          <article className="ai-operating-card">
            <span className="ai-section-label">Playbook method</span>
            <h4>Ask four questions for every outcome.</h4>
            <ol>
              <li><span>01</span><div><strong>Applicability</strong><small>Is this relevant to the system and its context?</small></div></li>
              <li><span>02</span><div><strong>Accountability</strong><small>Which team owns or supports the outcome?</small></div></li>
              <li><span>03</span><div><strong>Evidence</strong><small>How is the practice performed and documented?</small></div></li>
              <li><span>04</span><div><strong>Decision</strong><small>If it is missing, should the organization implement it?</small></div></li>
            </ol>
          </article>
        </div>
      </section>

      <section className="ai-research-section" id="patterns">
        <div className="ai-research-heading">
          <div><span className="ai-section-label">Adoption patterns</span><h3>Learn from programs already in motion</h3></div>
          <p>NIST lists community submissions as examples, not endorsements. Together they show that useful implementation starts with context, owners, evidence and iteration.</p>
        </div>
        <div className="ai-pattern-layout">
          <div className="ai-maturity-card">
            <span className="ai-section-label">A practical maturity scale</span>
            <h4>Progress is more useful than false perfection.</h4>
            <div className="ai-maturity-track">
              <div><span>1</span><strong>New</strong><small>No action yet</small></div>
              <div><span>2</span><strong>Planned</strong><small>Setting up</small></div>
              <div><span>3</span><strong>Established</strong><small>Operating</small></div>
              <div><span>4</span><strong>Adaptive</strong><small>Improving</small></div>
            </div>
            <p>San José used a four-level assessment to expose concrete gaps in policy, training, feedback, testing and decommissioning.</p>
          </div>
          <div className="ai-usecase-grid">
            {USE_CASES.map((item) => (
              <a href={item.href} target="_blank" rel="noreferrer" key={item.title}>
                <span>{item.sector}</span><strong>{item.title}</strong><small>{item.note}</small><i aria-hidden="true">↗</i>
              </a>
            ))}
          </div>
        </div>
        <a className="ai-source-cta" href="https://airc.nist.gov/airmf-resources/usecases/" target="_blank" rel="noreferrer">See NIST’s full list of use cases <span aria-hidden="true">↗</span></a>
      </section>

      <section className="ai-crosswalk-band">
        <div><span className="ai-section-label">Interoperability</span><h3>Map once. Reuse the evidence.</h3><p>Community crosswalks help connect AI RMF outcomes to other standards without implying that either framework provides complete coverage of the other.</p></div>
        <div className="ai-crosswalk-chips">{CROSSWALKS.map((item) => <span key={item}>{item}</span>)}</div>
        <a href="https://airc.nist.gov/airmf-resources/crosswalks/" target="_blank" rel="noreferrer">See all crosswalks <span aria-hidden="true">↗</span></a>
      </section>

      <section className="ai-research-section" id="library">
        <div className="ai-research-heading">
          <div><span className="ai-section-label">Technical depth</span><h3>Use the right guidance for the risk</h3></div>
          <p>The RMF is the organizing layer. NIST’s technical publications add the measurement, security, provenance, bias and explainability detail needed to operate it.</p>
        </div>
        <div className="ai-library-grid">
          {TECHNICAL_GUIDES.map((guide) => (
            <a href={guide.href} target="_blank" rel="noreferrer" key={guide.code}>
              <span>{guide.code}</span><h4>{guide.title}</h4><p>{guide.note}</p><i>Read guidance ↗</i>
            </a>
          ))}
        </div>
        <div className="ai-library-footer">
          <a href="https://airc.nist.gov/technical-reports/" target="_blank" rel="noreferrer">Browse all NIST technical reports <span aria-hidden="true">↗</span></a>
          <a href="https://airc.nist.gov/airmf-resources/airmf/" target="_blank" rel="noreferrer">View the AI RMF online <span aria-hidden="true">↗</span></a>
        </div>
      </section>
    </div>
  );
}
