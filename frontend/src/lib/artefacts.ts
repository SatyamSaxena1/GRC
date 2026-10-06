// Must match app/routers/evidence.py::ARTEFACT_TYPES and the artefact_type
// values the content packs match on — see app/content/*.yaml. AI_POLICY and
// AI_INVENTORY are what NIST-AI-RMF evidences against; an AI governance policy
// is deliberately not a POLICY, so uploading the security policy cannot
// accidentally satisfy an AI clause. CERTIFICATE and SCREENSHOT have no
// evidence_requirements mapped yet — they upload and classify but won't
// produce any framework links until a content pack maps them to one.
export const ARTEFACT_TYPES = [
  "POLICY", "ENCRYPTION_POLICY", "LOGGING_POLICY", "SCAN_REPORT", "REVIEW_RECORD", "REPORT", "CERTIFICATE", "SCREENSHOT",
  "AI_POLICY", "AI_INVENTORY", "PRIVACY_NOTICE",
];

export const ARTEFACT_LABELS: Record<string, string> = {
  POLICY: "Policies & procedures",
  ENCRYPTION_POLICY: "Encryption policies",
  LOGGING_POLICY: "Logging policies",
  SCAN_REPORT: "Scan reports",
  REVIEW_RECORD: "Review records",
  REPORT: "Reports",
  CERTIFICATE: "Certificates",
  SCREENSHOT: "Screenshots",
  AI_POLICY: "AI governance policies",
  AI_INVENTORY: "AI system inventories",
  PRIVACY_NOTICE: "Privacy notices",
};
