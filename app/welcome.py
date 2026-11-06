"""The welcome email a person gets once, when they are invited (ADR-052).

A deliberately small, deterministic stand-in for a support desk until a real support pipeline exists: it says who invited
them, gives the sign-in link when there is one, lists the first steps for THEIR role, and tells them that replying reaches a
person. No model writes it, nothing in it comes from evidence, and it is sent only at sign-up, never as a reminder.
"""

from __future__ import annotations

# role -> (what they can do here, first steps). Written plainly; the platform's own page names are used so a person can find them.
ROLE_HELP: dict[str, tuple[str, list[str]]] = {
    "ORG_ADMIN": (
        "You are an organisation admin: you set up how evidence reaches GRC and who works on it.",
        [
            "Open Connections and connect your team chat (Discord or Slack) so alerts and the Monday summary reach you.",
            "On the same page, connect GitHub, and send AWS, Microsoft 365 or HR evidence from your own scripts if you use them.",
            "Open Admin and invite your team. Each person gets this kind of email with their own first steps.",
            "Open Overview to see where compliance stands, and Gaps to see what needs doing first.",
        ],
    ),
    "CONTROL_OWNER": (
        "You are a control owner: you look after specific controls and the evidence behind them.",
        [
            "Open Tasks: anything assigned to you is there, with what is needed and by when.",
            "Open Evidence to upload a document (a policy, a report). GRC reads it and shows which requirements it meets.",
            "Open Gaps to see, in plain words, what a requirement still needs.",
            "When a control is ready, submit it for your auditor's review from its page.",
        ],
    ),
    "COMPLIANCE_VIEWER": (
        "You have read-only access: you can see where compliance stands, but not change anything.",
        [
            "Open Overview for the current picture, Controls for each requirement and its verdict.",
            "Open Reports for the weekly summary, and the trust page if your organisation publishes one.",
        ],
    ),
    "FIRM_ADMIN": (
        "You are an audit firm admin: you manage your auditors and the clients they work with.",
        [
            "Open your clients to open an engagement, and invite your auditors from Admin.",
            "Each auditor reviews controls and records a verdict with a written reason; the control then locks.",
        ],
    ),
    "AUDITOR": (
        "You are an auditor: you review the evidence behind controls and record your own verdict.",
        [
            "Open your review queue for the controls waiting on you.",
            "Read the evidence and the rule that judged it, then record your verdict with a written reason. The control locks.",
        ],
    ),
}
_FALLBACK = ("You have been given access to GRC.", ["Sign in and open Overview to see where things stand."])


def compose(role: str, org_name: str = "", link: str | None = None, app_url: str = "",
            support_reply: bool = True) -> tuple[str, str]:
    """(subject, plain-text body). `link` is the one-time password link when a login was just created for them."""
    intro, steps = ROLE_HELP.get(role, _FALLBACK)
    where = f" for {org_name}" if org_name else ""
    lines = [f"Hello,", "", f"You have been invited to GRC{where}, a platform that turns your evidence into compliance verdicts.", ""]
    if link:
        lines += ["First, choose your password with this one-time link. It stops working after seven days:", "", link, ""]
    elif app_url:
        lines += [f"Sign in here: {app_url}", ""]
    lines += [intro, "", "Your first steps:"]
    lines += [f"  {i}. {s}" for i, s in enumerate(steps, 1)]
    lines += [""]
    if support_reply:
        lines += ["Stuck, or not sure what something means? Reply to this email and a person will help you.", ""]
    lines += ["If you were not expecting this invitation, you can ignore this email."]
    return "Welcome to GRC: your first steps", "\n".join(lines) + "\n"
