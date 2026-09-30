// The golden-corpus document (evaluation/dataset/access_control_policy_v1.txt).
// Uploading this one is what makes the pitch concrete: 8 characters satisfies
// ISO 27001 A.5.15 and fails PCI DSS 8.3.6, from a single artefact.
export const POLICY_TEXT = `ASTERON SYSTEMS PVT. LTD. — ACCESS CONTROL POLICY
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
