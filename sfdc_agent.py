"""
SFDC Deduplication Agent - Main Orchestrator
Uses Claude Agent SDK to autonomously process contact deduplication and email validation
Integrated with LangSmith for observability
"""

import json
import os
from datetime import datetime
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
import agent_tools
from langsmith_wrapper import save_cost_report, get_cost_summary

# Load environment variables
load_dotenv()


class SFDCDeduplicationAgent:
    """
    Main agent orchestrator for SFDC contact deduplication and email validation.
    Processes contacts grouped by Account Owner for distributed review.
    """

    def __init__(self, batch_size=None, output_dir="reports", auto_approve=False):
        self.claude_client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        self.sf_connection = None
        self.batch_size = batch_size
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.auto_approve = auto_approve

        # Progress tracking
        self.checkpoint_file = self.output_dir / "agent_checkpoint.json"
        self.metrics = {
            "start_time": None,
            "end_time": None,
            "total_contacts": 0,
            "total_owners": 0,
            "emails_validated": 0,
            "duplicates_found": 0,
            "sfdc_updates": 0,
            "errors": []
        }

    def run(self):
        """
        Main agent workflow - processes all 6 phases with human approval gates.
        """
        print("=" * 70)
        print("SFDC CONTACT DEDUPLICATION & EMAIL VALIDATION AGENT")
        print("=" * 70)

        self.metrics["start_time"] = datetime.now().isoformat()

        try:
            # PHASE 1: Connect to Salesforce
            print("\n[PHASE 1] Connecting to Salesforce...")
            sf_result = agent_tools.connect_to_salesforce()

            if sf_result["status"] != "success":
                print(f"[ERROR] {sf_result['message']}")
                return

            self.sf_connection = sf_result["connection"]
            print(f"[OK] {sf_result['message']}")

            # PHASE 2: Extract Contacts (grouped by Account Owner)
            print("\n[PHASE 2] Extracting contacts grouped by Account Owner...")
            extraction_result = agent_tools.extract_contacts(
                self.sf_connection,
                batch_size=self.batch_size
            )

            if extraction_result["status"] != "success":
                print(f"[ERROR] {extraction_result['message']}")
                return

            self.metrics["total_contacts"] = extraction_result["total_contacts"]
            self.metrics["total_owners"] = extraction_result["owner_count"]

            print(f"[OK] Retrieved {extraction_result['total_contacts']} contacts")
            print(f"[OK] Grouped into {extraction_result['owner_count']} Account Owners:")

            for owner_id, metadata in extraction_result["owner_metadata"].items():
                print(f"     - {metadata['owner_name']}: {metadata['contact_count']} contacts")

            # Save checkpoint
            self._save_checkpoint("extraction", extraction_result)

            # PHASE 3: Email Validation
            print("\n[PHASE 3] Validating email addresses...")

            contact_ids = [c['Id'] for c in extraction_result['all_contacts']]
            activities = agent_tools.extract_email_activities(self.sf_connection, contact_ids)

            validation_result = agent_tools.validate_emails(
                extraction_result['all_contacts'],
                activities
            )

            print(f"[OK] Email validation complete:")
            print(f"     - Valid: {validation_result['stats']['Valid']}")
            print(f"     - Invalid: {validation_result['stats']['Invalid']}")
            print(f"     - Unknown: {validation_result['stats']['Unknown']}")
            print(f"     - Updates needed: {validation_result['updates_needed']}")

            self.metrics["emails_validated"] = validation_result["total_processed"]

            # Save checkpoint
            self._save_checkpoint("email_validation", validation_result)

            # PHASE 4: Duplicate Detection (parallel by owner)
            print("\n[PHASE 4] Detecting duplicates per Account Owner...")

            all_duplicate_pairs = []
            duplicates_by_owner = {}

            for owner_id, owner_contacts in extraction_result["contacts_by_owner"].items():
                owner_name = extraction_result["owner_metadata"][owner_id]["owner_name"]

                print(f"  Analyzing {owner_name} ({len(owner_contacts)} contacts)...")

                dup_result = agent_tools.detect_duplicates_for_owner(
                    owner_id,
                    owner_contacts,
                    self.claude_client
                )

                if dup_result["total_pairs"] > 0:
                    print(f"    -> Found {dup_result['total_pairs']} duplicate pair(s)")
                    all_duplicate_pairs.extend(dup_result["duplicate_pairs"])

                    duplicates_by_owner[owner_id] = {
                        "owner_name": owner_name,
                        "duplicate_pairs": dup_result["duplicate_pairs"]
                    }
                else:
                    print(f"    -> No duplicates found")

            print(f"\n[OK] Total duplicate pairs found: {len(all_duplicate_pairs)}")
            self.metrics["duplicates_found"] = len(all_duplicate_pairs)

            # Save checkpoint
            self._save_checkpoint("duplicate_detection", {
                "all_duplicate_pairs": all_duplicate_pairs,
                "duplicates_by_owner": duplicates_by_owner
            })

            # PHASE 5: Mark Duplicates for Review
            if len(all_duplicate_pairs) > 0:
                print("\n[PHASE 5] Preparing duplicate marking...")

                contacts_dict = {c['Id']: c for c in extraction_result['all_contacts']}

                marking_result = agent_tools.mark_duplicates_for_review(
                    all_duplicate_pairs,
                    contacts_dict
                )

                print(f"[OK] Prepared {marking_result['total_updates']} contact updates")
                print(f"[OK] Created {marking_result['duplicate_groups']} duplicate groups")

                # Preview for human approval
                print("\n" + "=" * 70)
                print("HUMAN APPROVAL REQUIRED")
                print("=" * 70)
                print(f"\nReady to mark {marking_result['total_updates']} contacts as duplicates.")
                print(f"This will update the following fields in Salesforce:")
                print("  - Email_Status__c = 'Duplicate'")
                print("  - Duplicate_Group_Name__c")
                print("  - Duplicate_Justification__c")
                print("  - Suggested_Action__c")
                print("  - Duplicate_Reviewed__c = FALSE")

                # Show sample if available
                if marking_result['decisions']:
                    print("\nSample duplicate group:")
                    sample_decision = marking_result['decisions'][0]
                    self._print_duplicate_decision(sample_decision)

                if self.auto_approve:
                    proceed = 'yes'
                    print("\n[AUTO-APPROVE] Proceeding with duplicate marking...")
                else:
                    proceed = input("\nProceed with marking duplicates in Salesforce? (yes/no): ").strip().lower()

                    if proceed != 'yes':
                        print("[INFO] Duplicate marking cancelled by user")
                        print("[INFO] Agent stopped. No changes made to Salesforce.")
                        return

                # Combine email validation + duplicate marking updates
                all_updates = validation_result['updates'] + marking_result['updates']

            else:
                print("\n[PHASE 5] No duplicates to mark")
                all_updates = validation_result['updates']

            # PHASE 6: Update Salesforce
            if len(all_updates) > 0:
                print("\n[PHASE 6] Updating Salesforce...")
                print(f"\nTotal updates to perform: {len(all_updates)}")

                print("\n" + "=" * 70)
                print("FINAL APPROVAL REQUIRED")
                print("=" * 70)
                print(f"\nReady to update {len(all_updates)} contacts in Salesforce.")

                if self.auto_approve:
                    proceed = 'yes'
                    print("\n[AUTO-APPROVE] Proceeding with Salesforce update...")
                else:
                    proceed = input("\nProceed with Salesforce update? (yes/no): ").strip().lower()

                    if proceed != 'yes':
                        print("[INFO] Salesforce update cancelled by user")
                        print("[INFO] Agent stopped. No changes made to Salesforce.")
                        return

                update_result = agent_tools.update_salesforce_contacts(
                    self.sf_connection,
                    all_updates
                )

                print(f"\n[OK] Salesforce update complete:")
                print(f"     - Success: {update_result['success_count']}")
                print(f"     - Errors: {update_result['error_count']}")

                self.metrics["sfdc_updates"] = update_result["success_count"]

                if update_result["error_count"] > 0:
                    self.metrics["errors"] = update_result["errors"]

            else:
                print("\n[PHASE 6] No Salesforce updates needed")

            # PHASE 7: Generate Reports per Owner
            print("\n[PHASE 7] Generating reports per Account Owner...")

            if len(all_duplicate_pairs) > 0:
                self._generate_owner_reports(duplicates_by_owner, contacts_dict, marking_result)

            # Generate master summary
            self._generate_master_summary(extraction_result, validation_result, marking_result if len(all_duplicate_pairs) > 0 else None)

            # Final metrics
            self.metrics["end_time"] = datetime.now().isoformat()

            print("\n" + "=" * 70)
            print("AGENT WORKFLOW COMPLETE")
            print("=" * 70)
            print(f"\nSummary:")
            print(f"  - Contacts processed: {self.metrics['total_contacts']}")
            print(f"  - Account Owners: {self.metrics['total_owners']}")
            print(f"  - Emails validated: {self.metrics['emails_validated']}")
            print(f"  - Duplicates found: {self.metrics['duplicates_found']}")
            print(f"  - Salesforce updates: {self.metrics['sfdc_updates']}")
            print(f"\nReports saved to: {self.output_dir}/")

            # Save LangSmith cost report
            print("\n[LANGSMITH] Saving cost report...")
            cost_summary = save_cost_report(output_dir=str(self.output_dir))
            print(f"\nCost Summary:")
            print(f"  - Total Cost: ${cost_summary['total_cost']}")
            print(f"  - Total Tokens: {cost_summary['total_tokens']:,}")
            print(f"  - Runtime: {cost_summary['runtime_seconds']}s")
            print(f"  - Cost/Minute: ${cost_summary['cost_per_minute']}")
            print(f"\nCost by Phase:")
            for phase, stats in cost_summary['calls_by_phase'].items():
                if stats['count'] > 0:
                    print(f"  - {phase}: {stats['count']} calls, ${stats['cost']:.4f}, {stats['tokens']} tokens")

        except Exception as e:
            print(f"\n[ERROR] Agent failed: {str(e)}")
            self.metrics["errors"].append(str(e))
            raise

    def _print_duplicate_decision(self, decision):
        """Print a formatted duplicate decision"""
        print(f"\nAccount: {decision['account_name']}")
        print(f"Confidence: {decision['confidence'].upper()}")
        print(f"Group Name: {decision['canonical_name']}")
        print(f"\nContact A:")
        print(f"  Name: {decision['contact_1']['name']}")
        print(f"  Email: {decision['contact_1']['email']}")
        print(f"  Justification: {decision['contact_1']['justification']}")
        print(f"  Suggested Action: {decision['contact_1']['suggested_action']}")
        print(f"\nContact B:")
        print(f"  Name: {decision['contact_2']['name']}")
        print(f"  Email: {decision['contact_2']['email']}")
        print(f"  Justification: {decision['contact_2']['justification']}")
        print(f"  Suggested Action: {decision['contact_2']['suggested_action']}")

    def _save_checkpoint(self, phase, data):
        """Save checkpoint data"""
        checkpoint = {
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }

        with open(self.checkpoint_file, 'w') as f:
            json.dump(checkpoint, f, indent=2, default=str)

    def _generate_owner_reports(self, duplicates_by_owner, contacts_dict, marking_result):
        """Generate separate Markdown report for each Account Owner"""
        for owner_id, owner_data in duplicates_by_owner.items():
            owner_name = owner_data["owner_name"]
            safe_name = owner_name.replace(" ", "_").replace("/", "_")

            report_file = self.output_dir / f"{safe_name}_duplicates.md"

            # Generate markdown report
            report = []
            report.append(f"# Duplicate Contacts Report - {owner_name}")
            report.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            report.append(f"\n**Total Duplicate Pairs: {len(owner_data['duplicate_pairs'])}**")
            report.append("\n---\n")

            # Find decisions for this owner
            owner_decisions = [
                d for d in marking_result['decisions']
                if any(pair['contact_id_1'] == d['contact_1']['id'] or pair['contact_id_2'] == d['contact_2']['id']
                       for pair in owner_data['duplicate_pairs'])
            ]

            for idx, decision in enumerate(owner_decisions, 1):
                report.append(f"## Duplicate Pair #{idx} - {decision['confidence'].upper()} Confidence\n")
                report.append(f"**Account:** {decision['account_name']}")
                report.append(f"**Group Name:** {decision['canonical_name']}")
                report.append(f"**AI Reasoning:** {decision['reasoning']}\n")

                report.append("| Field | Contact A | Contact B |")
                report.append("|-------|-----------|-----------|")
                report.append(f"| **Name** | {decision['contact_1']['name']} | {decision['contact_2']['name']} |")
                report.append(f"| **Email** | {decision['contact_1']['email']} | {decision['contact_2']['email']} |")
                report.append(f"| **Phone** | {decision['contact_1']['phone']} | {decision['contact_2']['phone']} |")
                report.append(f"| **Title** | {decision['contact_1']['title']} | {decision['contact_2']['title']} |")
                report.append(f"| **Justification** | {decision['contact_1']['justification']} | {decision['contact_2']['justification']} |")
                report.append(f"| **Suggested Action** | {decision['contact_1']['suggested_action']} | {decision['contact_2']['suggested_action']} |")
                report.append(f"| **SFDC ID** | `{decision['contact_1']['id']}` | `{decision['contact_2']['id']}` |\n")

                report.append("**Next Steps:**")
                report.append("1. Review both contacts in Salesforce")
                report.append("2. Verify the suggested action is correct")
                report.append("3. Update `Suggested_Action__c` field if needed")
                report.append("4. Check `Duplicate_Reviewed__c` checkbox to mark as reviewed")
                report.append("\n---\n")

            with open(report_file, 'w') as f:
                f.write('\n'.join(report))

            print(f"  [OK] Generated report for {owner_name}: {report_file}")

    def _generate_master_summary(self, extraction_result, validation_result, marking_result):
        """Generate master summary JSON file"""
        summary = {
            "generated_at": datetime.now().isoformat(),
            "metrics": self.metrics,
            "account_owners": extraction_result["owner_metadata"],
            "email_validation_stats": validation_result["stats"],
            "duplicate_detection": {
                "total_pairs": marking_result["duplicate_groups"] if marking_result else 0,
                "by_confidence": self._count_by_confidence(marking_result["decisions"]) if marking_result else {}
            }
        }

        summary_file = self.output_dir / "master_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

        print(f"  [OK] Generated master summary: {summary_file}")

    def _count_by_confidence(self, decisions):
        """Count duplicate pairs by confidence level"""
        counts = {"high": 0, "medium": 0, "low": 0}
        for decision in decisions:
            confidence = decision.get("confidence", "low").lower()
            counts[confidence] = counts.get(confidence, 0) + 1
        return counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SFDC Contact Deduplication & Email Validation Agent")
    parser.add_argument("--batch-size", type=int, help="Limit number of contacts to process (for testing)")
    parser.add_argument("--output-dir", default="reports", help="Directory for output reports")
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve all checkpoints (non-interactive)")

    args = parser.parse_args()

    agent = SFDCDeduplicationAgent(
        batch_size=args.batch_size,
        output_dir=args.output_dir,
        auto_approve=args.auto_approve
    )

    agent.run()
