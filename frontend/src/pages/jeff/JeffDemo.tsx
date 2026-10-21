import { useEffect } from "react";
import run from "./demo-run.json";

// A guided, screen-reader-first walk-through of one real demo run, for a prospect
// to explore before a call. Public like /pitch: it shows a frozen snapshot of a
// seeded demo organisation (scripts/seed_ai_demo.py), never live tenant data.
// Accessibility rules followed here: one h1, a heading per step, a skip link,
// verdicts always written as words (never colour alone), tables with captions
// and header scopes, and no motion.

type Verdict = {
  framework: string; clause: string; title: string; verdict: string; locked: boolean;
  auditor_verdict: string | null; rule_hash: string; gaps: string[];
};
type Fact = { name: string; value: unknown; quote: string | null };

const STEPS = [
  ["start", "How to use this page"],
  ["story", "Step 1. The story: an AI agent that buys things"],
  ["read", "Step 2. The model reads the policy, and only reads it"],
  ["judge", "Step 3. Fixed rules decide, clause by clause"],
  ["fix", "Step 4. Version 2: gaps close, one carries forward"],
  ["own", "Step 5. Who owns the decision: the auditor signs off"],
  ["replay", "Step 6. Replay: the same answer, months later"],
  ["code", "Step 7. AI code review is evidence, never approval"],
  ["verify", "Step 8. Check our records without trusting us"],
  ["next", "What happens next"],
] as const;

const human = (name: string) => name.replace(/_/g, " ");
const show = (value: unknown) =>
  Array.isArray(value) ? value.join(", ") : value === true ? "yes" : value === false ? "no" : String(value);
const verdictWords: Record<string, string> = {
  PASS: "Pass", PARTIAL: "Partly met", FAIL: "Fail",
};

function VerdictTable({ caption, rows, compare }: { caption: string; rows: Verdict[]; compare?: Verdict[] }) {
  const before = new Map((compare ?? []).map((r) => [r.clause, r.verdict]));
  return (
    <table>
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Clause</th>
          <th scope="col">What it asks for</th>
          {compare && <th scope="col">Version 1</th>}
          <th scope="col">{compare ? "Version 2" : "Verdict"}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.clause}>
            <th scope="row">{r.framework === "NIST-AI-RMF" ? r.clause : `${r.framework.replace("-", " ")} ${r.clause}`}</th>
            <td>{r.title}</td>
            {compare && <td>{verdictWords[before.get(r.clause) ?? ""] ?? "not assessed"}</td>}
            <td>
              {verdictWords[r.verdict] ?? r.verdict}
              {r.locked && ", locked by the auditor"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function JeffDemoPage() {
  useEffect(() => {
    document.title = "Guided demo for Jeff | GRC platform";
    const robots = document.createElement("meta");
    robots.name = "robots";
    robots.content = "noindex";
    document.head.appendChild(robots);
    return () => robots.remove();
  }, []);

  const v1 = run.policy_v1.verdicts as Verdict[];
  const v2 = run.policy_v2.verdicts as Verdict[];
  const facts = run.policy_v2.facts as Fact[];
  const cc = run.change_control.verdicts as Verdict[];
  const ccFacts = Object.fromEntries((run.change_control.facts as Fact[]).map((f) => [f.name, f.value]));
  const locked = v2.find((r) => r.locked);
  const fairness = v2.find((r) => r.clause === "GOVERN 1.2");
  const counts = (rows: Verdict[]) => ({
    pass: rows.filter((r) => r.verdict === "PASS").length,
    partial: rows.filter((r) => r.verdict === "PARTIAL").length,
    fail: rows.filter((r) => r.verdict === "FAIL").length,
  });
  const c1 = counts(v1);
  const c2 = counts(v2);
  const replay = run.replay as { recorded: { verdict: string }; under_current_rules: { verdict: string }; rules_changed_since: boolean } | null;

  return (
    <div className="jeff">
      <style>{CSS}</style>
      <a className="jeff-skip" href="#main">Skip to the walk-through</a>
      <header>
        <p className="jeff-kicker">Prepared for Jeff Pledger, CyberAI, ahead of our call</p>
        <h1>Who owns the AI decision? A guided demo you can explore on your own</h1>
      </header>

      <nav aria-labelledby="contents-heading">
        <h2 id="contents-heading">Contents</h2>
        <ol>
          {STEPS.map(([id, label]) => (
            <li key={id}><a href={`#${id}`}>{label}</a></li>
          ))}
        </ol>
      </nav>

      <main id="main" tabIndex={-1}>
        <section aria-labelledby="start">
          <h2 id="start">How to use this page</h2>
          <p>
            This page walks through one real run of the platform, recorded on {run.run_date}. Every verdict, quote and
            number below is what the software actually produced. Nothing is mocked up. On our call I will run the same
            steps live, and you can tell me where to click.
          </p>
          <p>
            The page is built for screen readers. Each step is a level 2 heading, so you can jump between steps with your
            heading key. Results are in tables with column and row headers. Verdicts are always written as words: Pass,
            Partly met, or Fail. Long documents are inside collapsed sections you can expand.
          </p>
        </section>

        <section aria-labelledby="story">
          <h2 id="story">Step 1. The story: an AI agent that buys things</h2>
          <p>
            Asteron, a made-up company, lets an AI agent approve vendor purchases. Your line fits it exactly: they know
            which AI made the purchase, but do they know who owns the decision? Asteron's AI governance policy is the
            evidence. We check it against the NIST AI Risk Management Framework, the GOVERN function.
          </p>
          <details>
            <summary>Read Asteron's AI governance policy, version 1</summary>
            <pre>{run.policy_v1.text}</pre>
          </details>
        </section>

        <section aria-labelledby="read">
          <h2 id="read">Step 2. The model reads the policy, and only reads it</h2>
          <p>
            An AI model reads the document and pulls out facts. Every fact keeps the exact sentence it came from, so a
            person can check it. The model never decides whether anything passes. Here are the facts it pulled from
            version 2 of the policy.
          </p>
          <table>
            <caption>Facts the model extracted from policy version 2, with the sentence each came from</caption>
            <thead>
              <tr><th scope="col">Fact</th><th scope="col">Value</th><th scope="col">Source sentence</th></tr>
            </thead>
            <tbody>
              {facts.map((f) => (
                <tr key={f.name}>
                  <th scope="row">{human(f.name)}</th>
                  <td>{show(f.value)}</td>
                  <td>{f.quote ?? "no quote recorded"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section aria-labelledby="judge">
          <h2 id="judge">Step 3. Fixed rules decide, clause by clause</h2>
          <p>
            Ordinary code, not the model, compares those facts with each clause. Version 1 of the policy got {c1.pass} passes,{" "}
            {c1.partial} partly met and {c1.fail} fail out of {v1.length} clauses. It names an owner and an overseer for
            every AI system. But it never says who can override the agent, how a decision escalates, or how an AI system
            is retired, and its list of trustworthy-AI qualities leaves out fairness.
          </p>
          <VerdictTable caption="NIST AI RMF verdicts for policy version 1" rows={v1} />
        </section>

        <section aria-labelledby="fix">
          <h2 id="fix">Step 4. Version 2: gaps close, one carries forward</h2>
          <p>
            Asteron adds who can override or stop the agent, a defined escalation path, and a retirement process, then
            uploads the policy as a new version. Nothing is overwritten. Version 2 gets {c2.pass} passes, {c2.partial} partly
            met and {c2.fail} fail.
          </p>
          <ul>
            <li>Retiring AI systems, GOVERN 1.7, goes from Fail to Pass.</li>
            <li>Roles and escalation, GOVERN 2.1, goes from Partly met to Pass.</li>
            <li>
              Human oversight, GOVERN 3.2, stays Partly met even though the override gap closed. That is deliberate: a
              policy alone can only partly prove that oversight happens in practice.
            </li>
            <li>
              Fairness, GOVERN 1.2, is still missing. {fairness?.gaps[0] && `The rule says: ${fairness.gaps[0]}.`} The
              same gap is carried forward with its owner and due date, not raised a second time.
            </li>
          </ul>
          <VerdictTable caption="NIST AI RMF verdicts, version 1 compared with version 2" rows={v2} compare={v1} />
          <details>
            <summary>Read Asteron's AI governance policy, version 2</summary>
            <pre>{run.policy_v2.text}</pre>
          </details>
        </section>

        <section aria-labelledby="own">
          <h2 id="own">Step 5. Who owns the decision: the auditor signs off</h2>
          <p>
            A human auditor, from an outside audit firm, reviewed {locked ? `${locked.clause} ("${locked.title}")` : "a clause"}{" "}
            on version 2 and locked it as {locked ? verdictWords[locked.auditor_verdict ?? locked.verdict] ?? locked.verdict : "Pass"},
            with a written reason. The record now holds both answers side by side: what the rules decided, and what the
            named human decided. The human's sign-off never overwrites the machine's verdict, so a later reviewer sees
            exactly who decided what. Unlocking it again needs a stated reason, which is recorded too.
          </p>
          <p>
            One more safeguard: whoever uploaded a document cannot sign off on it. The platform blocks that and logs the
            attempt.
          </p>
        </section>

        <section aria-labelledby="replay">
          <h2 id="replay">Step 6. Replay: the same answer, months later</h2>
          <p>
            Every verdict records a fingerprint of the exact rule that produced it. Replaying the locked clause re-runs it
            on the same facts. In this run the recorded verdict was{" "}
            {verdictWords[replay?.recorded.verdict ?? ""] ?? "unavailable"} and the replay gave{" "}
            {verdictWords[replay?.under_current_rules.verdict ?? ""] ?? "unavailable"}.{" "}
            {replay?.rules_changed_since
              ? "The rule has changed since, and the platform says so."
              : "The rule has not changed since, and if it ever does, the verdict is flagged rather than silently rewritten."}
          </p>
        </section>

        <section aria-labelledby="code">
          <h2 id="code">Step 7. AI code review is evidence, never approval</h2>
          <p>
            We pointed the platform at a real code repository: this product's own, over the last 90 days. It is built
            mostly by one person working with AI tools, so it is an honest test of the question you write about.
          </p>
          <ul>
            <li>{show(ccFacts.merges_in_period)} changes were merged.</li>
            <li>{show(ccFacts.ai_assisted_merges)} of them were written with AI assistance.</li>
            <li>{show(ccFacts.merges_without_independent_approval)} had no independent human approval.</li>
          </ul>
          <p>
            AI reviewers looked at these changes, and the platform records that. But it does not count an AI review as an
            approval. So both clauses below are only partly met, and the reasons name every number that falls short.
          </p>
          <VerdictTable caption="Change-control verdicts for the real repository" rows={cc} />
          {cc.map((r) => (
            <details key={r.clause}>
              <summary>Why {r.framework.replace("-", " ")} {r.clause} is partly met: {r.gaps.length} reasons</summary>
              <ul>{r.gaps.map((g) => <li key={g}>{g.replace(/_/g, " ")}</li>)}</ul>
            </details>
          ))}
        </section>

        <section aria-labelledby="verify">
          <h2 id="verify">Step 8. Check our records without trusting us</h2>
          <p>
            Every action above, from upload to sign-off, is written to a chained log where each entry includes a
            fingerprint of the one before. This run's log has {run.chain.events} entries and checks out end to end. The
            auditor also took a signed checkpoint of the log and keeps it outside the platform. A small standalone
            script, with no access to our servers, checked the exported log against that checkpoint. It printed:
          </p>
          <p><q>{run.verify_output}</q></p>
          <p>If anyone edited history afterwards, that check would fail, and the auditor would know.</p>
        </section>

        <section aria-labelledby="next">
          <h2 id="next">What happens next</h2>
          <p>
            On our call I will run these steps live. You can choose what to upload, which clause to replay, or what to
            break. I would especially like your view on step 5: what would you want the record to show about who owns an
            AI decision that it does not show today?
          </p>
          <p>Satyam Saxena</p>
        </section>
      </main>
    </div>
  );
}

const CSS = `
.jeff { max-width: 52rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; font: 1.125rem/1.6 system-ui, sans-serif;
  color: #111; background: #fff; }
.jeff h1 { font-size: 1.9rem; line-height: 1.25; margin: .25rem 0 1.5rem; }
.jeff h2 { font-size: 1.4rem; margin: 2.5rem 0 .75rem; }
.jeff-kicker { margin: 0; color: #333; }
.jeff a { color: #0645ad; text-underline-offset: 3px; }
.jeff a:focus-visible, .jeff summary:focus-visible, .jeff main:focus-visible { outline: 3px solid #b35c00; outline-offset: 3px; }
.jeff-skip { position: absolute; left: -9999px; }
.jeff-skip:focus { left: 1rem; top: 1rem; background: #fff; padding: .5rem 1rem; border: 2px solid #111; z-index: 10; }
.jeff table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 1rem; }
.jeff caption { text-align: left; font-weight: 600; padding-bottom: .5rem; }
.jeff th, .jeff td { border: 1px solid #555; padding: .5rem; text-align: left; vertical-align: top; }
.jeff thead th { background: #eee; }
.jeff details { margin: 1rem 0; }
.jeff summary { cursor: pointer; font-weight: 600; }
.jeff pre { white-space: pre-wrap; font: 1rem/1.5 system-ui, sans-serif; background: #f6f6f6; padding: 1rem; }
`;
