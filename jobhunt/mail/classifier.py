"""Classify fetched emails via the LLM provider, match to applications,
auto-advance pipeline stages, and write audit-log entries."""
from __future__ import annotations

import re
from typing import Optional

from ..db import DB
from ..llm import get_provider


STAGE_ORDER = {
    "applied": 1,
    "screening": 2,
    "interview": 3,
    "offer": 4,
}

STAGE_TO_DB_NAME = {
    "applied": "Applied",
    "screening": "Screening",
    "interview": "Interview",
    "offer": "Offer",
    "rejected": "Rejected",
}


_NOREPLY_PREFIXES = (
    "careers.", "jobs.", "talent.", "mail.", "email.", "noreply.",
    "no-reply.", "do-not-reply.", "notifications.", "notify.",
)
_GENERIC_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com",
    "outlook.com", "live.com", "icloud.com", "me.com", "aol.com",
    "fastmail.com", "proton.me", "protonmail.com",
}


def _sender_domain_token(sender: str) -> Optional[str]:
    """Return the 'brand' portion of a sender address (e.g. 'stripe' from 'recruiter@stripe.com'),
    or None if the sender is from a generic personal-email provider."""
    m = re.search(r"<([^>]+)>", sender)
    addr = m.group(1) if m else sender
    if "@" not in addr:
        return None
    domain = addr.split("@")[-1].lower().strip()
    if domain in _GENERIC_DOMAINS:
        return None
    for prefix in _NOREPLY_PREFIXES:
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
            break
    parts = domain.split(".")
    if len(parts) >= 2:
        return parts[0]
    return None


def _match_application(
    sender: str, subject: str, body: str, llm_company: Optional[str]
) -> Optional[tuple[int, int]]:
    """Try to match an email to an existing application.
    Returns (application_id, score) or None."""
    rows = DB.query("SELECT id, company FROM applications")
    if not rows:
        return None

    sender_brand = _sender_domain_token(sender) or ""
    subject_lower = (subject or "").lower()
    body_head = (body or "")[:2000].lower()
    llm_company_lower = (llm_company or "").lower()

    best_id: Optional[int] = None
    best_score = 0

    for row in rows:
        company = (row["company"] or "").lower().strip()
        if not company:
            continue
        company_first_word = company.split()[0]

        score = 0
        if sender_brand and (
            company_first_word == sender_brand or sender_brand in company or company_first_word in sender_brand
        ):
            score += 10
        if llm_company_lower and company in llm_company_lower:
            score += 8
        if company in subject_lower:
            score += 5
        elif company_first_word in subject_lower and len(company_first_word) > 3:
            score += 3
        if company in body_head:
            score += 2

        if score > best_score:
            best_score = score
            best_id = row["id"]

    if best_score >= 5:
        return (best_id, best_score)
    return None


def _get_stage_id(stage_name: Optional[str]) -> Optional[int]:
    if not stage_name:
        return None
    row = DB.query_one("SELECT id FROM pipeline_stages WHERE name = ?", (stage_name,))
    return row["id"] if row else None


def _current_stage_name(application_id: int) -> Optional[str]:
    row = DB.query_one(
        """SELECT s.name FROM applications a
           LEFT JOIN pipeline_stages s ON s.id = a.current_stage_id
           WHERE a.id = ?""",
        (application_id,),
    )
    return row["name"] if row and row["name"] else None


def _should_advance(detected_stage: str, current_stage_name: Optional[str]) -> bool:
    if detected_stage in ("follow_up", "unrelated"):
        return False
    current = (current_stage_name or "").lower()
    if detected_stage == "rejected":
        return current != "rejected"
    detected_order = STAGE_ORDER.get(detected_stage, 0)
    current_order = STAGE_ORDER.get(current, 0)
    return detected_order > current_order


def classify_pending(max_emails: int = 50) -> dict:
    """Classify up to `max_emails` unprocessed emails. For each:
    - Call LLM provider.classify_email
    - Save detected_stage on the email row + mark processed_flag = 1
    - Try to match to an application; if matched, save application_id on email
    - If matched and stage transition is forward, advance the application's stage
    Returns a stats dict."""
    rows = DB.query(
        """SELECT id, subject, sender, raw_body
           FROM emails
           WHERE processed_flag = 0
           ORDER BY id ASC
           LIMIT ?""",
        (max_emails,),
    )
    stats = {
        "total": len(rows),
        "classified": 0,
        "matched": 0,
        "stage_updates": 0,
        "interviews_detected": 0,
        "errors": 0,
    }
    if not rows:
        return stats

    provider = get_provider()

    for row in rows:
        email_id = row["id"]
        subject = row["subject"] or ""
        sender = row["sender"] or ""
        body = row["raw_body"] or ""

        try:
            result = provider.classify_email(subject, body)
        except Exception as e:
            DB.log_audit("email_classify_error", {"email_id": email_id, "error": str(e)})
            stats["errors"] += 1
            continue

        stats["classified"] += 1

        DB.execute(
            "UPDATE emails SET detected_stage = ?, processed_flag = 1 WHERE id = ?",
            (result.stage, email_id),
        )

        match = _match_application(sender, subject, body, result.company)
        if match is None:
            continue
        application_id, match_score = match
        stats["matched"] += 1

        DB.execute(
            "UPDATE emails SET application_id = ? WHERE id = ?",
            (application_id, email_id),
        )

        current_stage = _current_stage_name(application_id)
        if _should_advance(result.stage, current_stage):
            new_stage_name = STAGE_TO_DB_NAME.get(result.stage)
            new_stage_id = _get_stage_id(new_stage_name)
            if new_stage_id is not None:
                DB.execute(
                    """UPDATE applications
                       SET current_stage_id = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (new_stage_id, application_id),
                )
                DB.log_audit("stage_advanced_from_email", {
                    "application_id": application_id,
                    "from": current_stage,
                    "to": new_stage_name,
                    "email_id": email_id,
                    "confidence": result.confidence,
                    "reason": result.reason,
                    "match_score": match_score,
                })
                stats["stage_updates"] += 1

        # Auto-create an interview row only if the classifier was confident
        # enough (≥ 0.7) — low-confidence guesses make for noisy interview
        # lists. Dedupe by (application_id, interview_datetime).
        if (
            result.stage == "interview"
            and result.interview_datetime
            and (result.confidence or 0.0) >= 0.7
        ):
            existing = DB.query_one(
                """SELECT id FROM interviews
                   WHERE application_id = ? AND interview_datetime = ?""",
                (application_id, result.interview_datetime),
            )
            if not existing:
                DB.execute(
                    """INSERT INTO interviews
                       (application_id, interview_datetime, round_type, prep_notes,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (application_id, result.interview_datetime,
                     "Detected from email", ""),
                )
                DB.log_audit("interview_detected_from_email", {
                    "application_id": application_id,
                    "datetime": result.interview_datetime,
                    "confidence": result.confidence,
                    "email_id": email_id,
                })
                stats["interviews_detected"] += 1

    return stats
