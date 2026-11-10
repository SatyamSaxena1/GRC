# ADR-037: Connector evidence counts toward framework controls

Status: accepted

## Context
AWS, Microsoft 365 and HR snapshots were read only by the DPDP pack. A workspace subscribed to ISO 27001,
SOC 2 and PCI DSS showed three controls (all from GitHub change control), although the same facts speak to
logging, multi-factor authentication and leaver access in those frameworks.

## Decision
Add eight clauses that read the existing snapshots, with no new collector and no new attribute:

| Framework | Clause | Snapshot | Fact | Coverage |
|---|---|---|---|---|
| ISO 27001 | A.8.5 Secure authentication | Microsoft 365 | privileged MFA | FULL |
| ISO 27001 | A.8.2 Privileged access rights | AWS | privileged MFA | PARTIAL |
| ISO 27001 | A.8.15 Logging | AWS | access logging | PARTIAL |
| SOC 2 | CC7.2 Monitoring of system components | AWS | access logging | PARTIAL |
| PCI DSS | 10.2.1 Audit logs enabled | AWS | access logging | PARTIAL |
| PCI DSS | 8.4.1 MFA for administrative access | AWS | privileged MFA | PARTIAL |
| PCI DSS | 8.4.3 MFA for remote access | Microsoft 365 | privileged MFA | FULL |
| PCI DSS | 8.2.5 Terminated users' access revoked | HR system | leavers with live accounts | FULL |

Coverage is stated honestly: a mapping is PARTIAL when the snapshot shows one facet of the clause (logging
is on; retention and review are not shown), and a PARTIAL mapping can only ever give a PARTIAL verdict. A
clause is left out when no snapshot covers it (ISO A.6.5 is about documented responsibilities, which a
leaver check cannot show).

**Added 2026-11-10 (issue 82, drafted by an AI, awaiting review, so `source: AI`):** ISO 27001 A.8.16 Monitoring
activities (AWS, access logging, SUPPORTING) and PCI DSS 3.5.1 PAN rendered unreadable where stored (AWS,
encryption at rest, PARTIAL: AWS shows encryption at rest only). Policy-evidenced clauses such as ISO A.5.26
incident response, A.8.10 deletion, PCI 3.2.1 and 12.10.1 were tried and left out: a POLICY clause asks every
uploaded policy for incident and retention facts, so an ordinary access-control policy started failing ISO and PCI.
**Then done properly (same day):** two new document types, INCIDENT_POLICY and RETENTION_POLICY (the same pattern as
ENCRYPTION_POLICY and LOGGING_POLICY), so ISO A.5.26, A.8.10 and PCI 3.2.1, 12.10.1 read the right kind of policy and
never fail an access-control policy. Also ISO A.8.13 Information backup (AWS, backups present, PARTIAL: AWS does not show a
restore was tested) on a new unified control UCO-DATA-002. All `source: AI`, awaiting review. SOC 2 CC6.5 and CC7.4 and
the DPDP clauses still read POLICY: moving them would change existing verdicts, so it needs its own decision. Two
policy templates (incident response, data retention) were added so an organisation can start from text that meets them.
Not drafted: ISO A.8.20 network security (we collect no such evidence). The Connections page now lists, for each source, the
clauses it counts toward, marking any still awaiting review.

Same rules as every other pack: versioned, deterministic, expert-sourced, confidence below 1.

## Consequences
- Existing rule hashes are unchanged; only new clauses were added.
- A subscribed workspace gains controls the first time one of these sources is collected.
- Attributes the snapshots do not carry (encryption in the AWS clause, backup) are not mapped to
  framework clauses yet; DPDP still reads them.
