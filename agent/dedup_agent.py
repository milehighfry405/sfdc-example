"""
SFDC Deduplication Agent - Workflow Runner
Adapted from sfdc_agent.py to work with FastAPI job management
"""

import json
import os
from datetime import datetime
from pathlib import Path
from anthropic import Anthropic

from agent import tools
from agent.config import config
from agent.langsmith_wrapper import save_cost_report, get_cost_summary


def run_agent_workflow(job_id: str, job_config: dict, job_manager=None):
    """
    Run the full agent workflow.
    This is called from FastAPI in a background thread.

    Args:
        job_id: Unique job identifier
        job_config: Job configuration from API request
        job_manager: JobManager instance for progress updates (optional)

    Returns:
        dict: Results including metrics and cost summary
    """

    # Initialize
    claude_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    sf_connection = None
    batch_size = job_config.get("batch_size")
    auto_approve = job_config.get("auto_approve", False)
    output_dir = Path(f"reports/job_{job_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "start_time": datetime.now().isoformat(),
        "total_contacts": 0,
        "total_owners": 0,
        "emails_validated": 0,
        "duplicates_found": 0,
        "sfdc_updates": 0,
        "errors": []
    }

    def update_progress(phase: str, step: int, message: str):
        """Helper to update job progress"""
        if job_manager:
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    job_manager.update_job(job_id, {
                        "progress": {
                            "phase": phase,
                            "current_step": step,
                            "total_steps": 7,
                            "message": message
                        }
                    })
                )
                loop.close()
            except Exception as e:
                print(f"Error updating progress: {e}")

    try:
        # PHASE 1: Connect to Salesforce
        update_progress("phase_1_connect", 1, "Connecting to Salesforce...")

        conn_result = tools.connect_to_salesforce()
        if conn_result["status"] != "success":
            raise Exception(conn_result["message"])

        sf_connection = conn_result["connection"]

        # PHASE 2: Extract Contacts
        update_progress("phase_2_extract", 2, "Extracting contacts grouped by Account Owner...")

        extraction_result = tools.extract_contacts(
            sf_connection,
            batch_size=batch_size,
            owner_filter=job_config.get("owner_filter")
        )

        if extraction_result["status"] != "success":
            raise Exception(extraction_result["message"])

        metrics["total_contacts"] = extraction_result["total_contacts"]
        metrics["total_owners"] = extraction_result["owner_count"]

        # Create contacts lookup dict
        contacts_dict = {c['Id']: c for c in extraction_result['all_contacts']}

        # PHASE 3: Email Validation
        update_progress("phase_3_validate", 3, f"Validating {metrics['total_contacts']} email addresses...")

        contact_ids = list(contacts_dict.keys())
        activities = tools.extract_email_activities(sf_connection, contact_ids)

        validation_result = tools.validate_emails(
            extraction_result['all_contacts'],
            activities
        )

        metrics["emails_validated"] = validation_result["total_processed"]

        # PHASE 4: Duplicate Detection
        update_progress("phase_4_detect", 4, f"Detecting duplicates across {metrics['total_owners']} Account Owners...")

        all_duplicate_pairs = []
        duplicates_by_owner = {}

        for owner_id, owner_contacts in extraction_result["contacts_by_owner"].items():
            owner_name = extraction_result["owner_metadata"][owner_id]["owner_name"]

            dup_result = tools.detect_duplicates_for_owner(
                owner_id,
                owner_contacts,
                claude_client
            )

            if dup_result["total_pairs"] > 0:
                all_duplicate_pairs.extend(dup_result["duplicate_pairs"])
                duplicates_by_owner[owner_id] = {
                    "owner_name": owner_name,
                    "duplicate_pairs": dup_result["duplicate_pairs"]
                }

        metrics["duplicates_found"] = len(all_duplicate_pairs)

        # PHASE 5: Prepare Duplicate Marking
        update_progress("phase_5_mark", 5, f"Preparing to mark {len(all_duplicate_pairs)} duplicate pairs...")

        marking_result = None
        all_updates = validation_result['updates']

        if len(all_duplicate_pairs) > 0:
            marking_result = tools.mark_duplicates_for_review(
                all_duplicate_pairs,
                contacts_dict
            )

            # If not auto_approve, wait for human approval
            if not auto_approve and job_manager:
                update_progress("awaiting_approval", 5, "Awaiting human approval for duplicate marking...")

                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Store pending approval in job state
                loop.run_until_complete(
                    job_manager.update_job(job_id, {
                        "status": "awaiting_approval",
                        "pending_approval": {
                            "stage": "duplicate_marking",
                            "total_updates": marking_result["total_updates"],
                            "decisions": marking_result["decisions"],
                            "message": f"Ready to mark {marking_result['total_updates']} contacts as duplicates"
                        }
                    })
                )

                # Wait for approval
                approved = wait_for_approval(job_id, job_manager, loop)
                loop.close()

                if not approved:
                    return {
                        "status": "cancelled",
                        "message": "Job cancelled by user",
                        "metrics": metrics
                    }

            # Add duplicate marking updates
            all_updates.extend(marking_result['updates'])

        # PHASE 6: Update Salesforce
        if len(all_updates) > 0:
            update_progress("phase_6_update", 6, f"Updating {len(all_updates)} contacts in Salesforce...")

            # If not auto_approve, wait for final approval
            if not auto_approve and job_manager:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                loop.run_until_complete(
                    job_manager.update_job(job_id, {
                        "status": "awaiting_approval",
                        "pending_approval": {
                            "stage": "salesforce_update",
                            "total_updates": len(all_updates),
                            "message": f"Ready to update {len(all_updates)} contacts in Salesforce"
                        }
                    })
                )

                approved = wait_for_approval(job_id, job_manager, loop)
                loop.close()

                if not approved:
                    return {
                        "status": "cancelled",
                        "message": "Job cancelled by user",
                        "metrics": metrics
                    }

            # Execute updates
            update_result = tools.update_salesforce_contacts(
                sf_connection,
                all_updates
            )

            metrics["sfdc_updates"] = update_result["success_count"]

            if update_result["error_count"] > 0:
                metrics["errors"] = update_result["errors"]

        # PHASE 7: Generate Reports
        update_progress("phase_7_reports", 7, "Generating reports...")

        if len(all_duplicate_pairs) > 0:
            _generate_owner_reports(
                duplicates_by_owner,
                contacts_dict,
                marking_result,
                output_dir
            )

        _generate_master_summary(
            extraction_result,
            validation_result,
            marking_result if len(all_duplicate_pairs) > 0 else None,
            metrics,
            output_dir
        )

        # Save cost report
        cost_summary = save_cost_report(output_dir=str(output_dir))

        # Final metrics
        metrics["end_time"] = datetime.now().isoformat()

        return {
            "status": "success",
            "metrics": metrics,
            "cost_summary": cost_summary,
            "reports_dir": str(output_dir),
            "duplicate_pairs_found": len(all_duplicate_pairs)
        }

    except Exception as e:
        metrics["errors"].append(str(e))
        raise


def wait_for_approval(job_id: str, job_manager, loop, timeout=3600):
    """
    Wait for user approval via API.
    Polls job state for approval decision.

    Args:
        job_id: Job ID
        job_manager: JobManager instance
        loop: asyncio event loop
        timeout: Timeout in seconds (default 1 hour)

    Returns:
        bool: True if approved, False if rejected
    """
    import time

    start_time = time.time()

    while time.time() - start_time < timeout:
        # Check for approval decision
        job = loop.run_until_complete(job_manager.get_job(job_id))

        if job and job.get("approval_decision"):
            decision = job["approval_decision"]
            return decision.get("approved", False)

        # Poll every 2 seconds
        time.sleep(2)

    # Timeout - reject by default
    return False


def _generate_owner_reports(duplicates_by_owner, contacts_dict, marking_result, output_dir):
    """Generate Markdown report for each Account Owner"""

    for owner_id, owner_data in duplicates_by_owner.items():
        owner_name = owner_data["owner_name"]
        safe_name = owner_name.replace(" ", "_").replace("/", "_")
        report_file = output_dir / f"{safe_name}_duplicates.md"

        report = []
        report.append(f"# Duplicate Contacts Report - {owner_name}")
        report.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"\nTotal Duplicate Groups: {len(owner_data['duplicate_pairs'])}")
        report.append("\n---\n")

        # Find decisions for this owner
        owner_decisions = [
            d for d in marking_result["decisions"]
            if any(
                contacts_dict.get(d['contact_1']['id'], {}).get('AccountOwnerId') == owner_id
                for d in marking_result["decisions"]
            )
        ]

        for idx, decision in enumerate(owner_decisions, 1):
            report.append(f"## Duplicate Group {idx}: {decision['canonical_name']}")
            report.append(f"\n**Account:** {decision['account_name']}")
            report.append(f"**Confidence:** {decision['confidence'].upper()}")
            report.append(f"\n**AI Reasoning:** {decision['reasoning']}")
            report.append("\n### Side-by-Side Comparison\n")

            # Contact A
            report.append("| Field | Contact A | Contact B |")
            report.append("|-------|-----------|-----------|")
            report.append(f"| Name | {decision['contact_1']['name']} | {decision['contact_2']['name']} |")
            report.append(f"| Email | {decision['contact_1']['email']} | {decision['contact_2']['email']} |")
            report.append(f"| Phone | {decision['contact_1']['phone']} | {decision['contact_2']['phone']} |")
            report.append(f"| Title | {decision['contact_1']['title']} | {decision['contact_2']['title']} |")
            report.append(f"| Suggested Action | **{decision['contact_1']['suggested_action']}** | **{decision['contact_2']['suggested_action']}** |")
            report.append(f"| Justification | {decision['contact_1']['justification']} | {decision['contact_2']['justification']} |")

            report.append("\n### Review Instructions\n")
            report.append("1. Review both contacts in Salesforce")
            report.append("2. Verify the suggested action is correct")
            report.append("3. Update `Suggested_Action__c` field if needed")
            report.append("4. Check `Duplicate_Reviewed__c` checkbox to mark as reviewed")
            report.append("\n---\n")

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))


def _generate_master_summary(extraction_result, validation_result, marking_result, metrics, output_dir):
    """Generate master summary JSON"""

    summary = {
        "generated_at": datetime.now().isoformat(),
        "metrics": metrics,
        "account_owners": extraction_result["owner_metadata"],
        "email_validation_stats": validation_result["stats"],
        "duplicate_detection": {
            "total_pairs": marking_result["duplicate_groups"] if marking_result else 0,
            "by_confidence": _count_by_confidence(marking_result["decisions"]) if marking_result else {}
        }
    }

    summary_file = output_dir / "master_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2, default=str)


def _count_by_confidence(decisions):
    """Count duplicate pairs by confidence level"""
    counts = {"high": 0, "medium": 0, "low": 0}
    for decision in decisions:
        confidence = decision.get("confidence", "low").lower()
        counts[confidence] = counts.get(confidence, 0) + 1
    return counts


def test_salesforce_connection():
    """Test Salesforce connection (used by health check)"""
    try:
        result = tools.connect_to_salesforce()
        return result["status"] == "success"
    except Exception:
        return False
