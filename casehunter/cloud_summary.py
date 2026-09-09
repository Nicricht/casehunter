import json
from pathlib import Path

from .auto_service import list_auto_runs
from .database import backend_name
from .operations import operations_snapshot
from .outreach import list_outreach


def build_cloud_summary(db_path=None, run_json_path="data/last-auto-run.json"):
    lines = ["# Case Hunter Auto Cloud", ""]
    lines.append(f"**Database backend:** {backend_name(db_path)}  ")

    runs = list_auto_runs(1, db_path)
    if runs:
        last = runs[0]
        lines.extend([
            f"**Run:** {last['id']}  ",
            f"**Status:** {last['status']}  ",
            f"**Cases created:** {last['cases_created']}  ",
            f"**Cases updated:** {last['cases_updated']}  ",
            f"**Contacts found:** {last['contacts_found']}  ",
            f"**Drafts created:** {last['drafts_created']}  ",
            f"**Messages sent:** {last['messages_sent']}  ",
        ])
        if last.get("error"):
            lines.append(f"**Error:** {last['error']}  ")

    operations = operations_snapshot(db_path)
    kpis = operations["kpis"]
    lines.extend([
        f"**Replies received:** {kpis['replies_received']}  ",
        f"**Follow-ups due:** {kpis['followups_due']}  ",
        f"**Cases resolved:** {kpis['cases_resolved']}  ",
        f"**Reply rate:** {kpis['reply_rate']:.1%}  ",
        f"**Resolution rate:** {kpis['resolution_rate']:.1%}  ",
    ])

    run_file = Path(run_json_path)
    if run_file.exists():
        try:
            payload = json.loads(run_file.read_text(encoding="utf-8"))
            policy = payload.get("policy_auto_send") or {}
            lines.extend([
                f"**Policy auto-send enabled:** {policy.get('enabled', False)}  ",
                f"**Policy auto-approved:** {policy.get('auto_approved', 0)}  ",
                f"**Policy auto-sent:** {policy.get('auto_sent', 0)}  ",
                f"**Daily first-contact limit:** {policy.get('daily_limit', 0)}  ",
            ])
        except (OSError, ValueError, TypeError):
            pass

    lines.extend(["", "## Top outreach queue"])
    queue = [
        row for row in list_outreach(db_path=db_path)
        if row.get("status") in {"READY_FOR_APPROVAL", "NEEDS_CONTACT", "APPROVED"}
    ][:20]
    if not queue:
        lines.append("No pending prospects in the queue yet.")
    else:
        lines.extend([
            "| Priority | Company | Contract | Status | Contact |",
            "|---:|---|---|---|---|",
        ])
        for row in queue:
            company = str(row.get("detected_company_name") or "").replace("|", "/")
            contract = str(row.get("contract_ref") or "").replace("|", "/")
            contact = row.get("recipient_email") or "pending"
            lines.append(
                f"| {row.get('financial_priority', 0)} | {company} | {contract} | {row.get('status')} | {contact} |"
            )

    return "\n".join(lines) + "\n"


def main():
    print(build_cloud_summary(), end="")


if __name__ == "__main__":
    main()
