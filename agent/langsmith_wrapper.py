"""
LangSmith Observability Wrapper
Instruments all Claude API calls with cost tracking, QA validation, and performance monitoring
"""

import os
import json
from datetime import datetime
from functools import wraps
from typing import Dict, Any, List
from langsmith import Client, traceable
from langsmith.run_helpers import get_current_run_tree
from dotenv import load_dotenv

load_dotenv()

# Initialize LangSmith client
langsmith_client = Client(
    api_key=os.getenv("LANGCHAIN_API_KEY"),
    api_url=os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
)

# Cost tracking (Claude pricing as of 2025)
CLAUDE_PRICING = {
    "claude-3-5-haiku-20241022": {
        "input": 0.80 / 1_000_000,   # $0.80 per million input tokens
        "output": 4.00 / 1_000_000    # $4.00 per million output tokens
    },
    "claude-sonnet-4-5-20250929": {
        "input": 3.00 / 1_000_000,
        "output": 15.00 / 1_000_000
    }
}


class CostTracker:
    """Track costs across all Claude API calls"""

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.calls_by_phase = {
            "duplicate_detection": {"count": 0, "cost": 0.0, "tokens": 0},
            "email_validation": {"count": 0, "cost": 0.0, "tokens": 0},
            "other": {"count": 0, "cost": 0.0, "tokens": 0}
        }
        self.start_time = datetime.now()

    def track_call(self, model: str, input_tokens: int, output_tokens: int, phase: str = "other"):
        """Track a single API call"""
        pricing = CLAUDE_PRICING.get(model, CLAUDE_PRICING["claude-3-5-haiku-20241022"])

        input_cost = input_tokens * pricing["input"]
        output_cost = output_tokens * pricing["output"]
        total_call_cost = input_cost + output_cost

        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += total_call_cost

        if phase in self.calls_by_phase:
            self.calls_by_phase[phase]["count"] += 1
            self.calls_by_phase[phase]["cost"] += total_call_cost
            self.calls_by_phase[phase]["tokens"] += (input_tokens + output_tokens)

        return total_call_cost

    def get_summary(self) -> Dict[str, Any]:
        """Get cost summary"""
        runtime = (datetime.now() - self.start_time).total_seconds()

        return {
            "total_cost": round(self.total_cost, 4),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "runtime_seconds": round(runtime, 2),
            "calls_by_phase": self.calls_by_phase,
            "cost_per_minute": round((self.total_cost / runtime) * 60, 4) if runtime > 0 else 0
        }


# Global cost tracker
cost_tracker = CostTracker()


@traceable(name="detect_duplicates_claude", tags=["duplicate-detection", "ai"])
def traced_duplicate_detection(owner_id: str, owner_name: str, formatted_contacts: List[Dict],
                                 claude_client, account_name: str) -> Dict[str, Any]:
    """
    Wrapped duplicate detection with LangSmith tracing.
    Captures inputs, outputs, costs, and metadata.
    """
    # Log inputs
    run = get_current_run_tree()
    if run:
        run.add_metadata({
            "owner_id": owner_id,
            "owner_name": owner_name,
            "account_name": account_name,
            "contact_count": len(formatted_contacts),
            "phase": "duplicate_detection"
        })

    prompt = f"""You are analyzing contacts from the Salesforce account "{account_name}" to identify DUPLICATE RECORDS OF THE SAME PERSON.

Here are the contacts:

{json.dumps(formatted_contacts, indent=2)}

CRITICAL: Only flag contacts as duplicates if they are likely THE SAME PERSON with multiple records.

DO NOT flag as duplicates:
- Different people who work at the same company
- Different people who share a company phone number
- Colleagues with different names, emails, and titles

DO flag as duplicates if you see:
1. **Name variations of same person**: "Ben Fry" vs "Benjamin Fry", "Bob Smith" vs "Robert Smith"
2. **Name typos**: "Ben Fry" vs "Ben Frye" (especially if titles/roles are similar)
3. **Email variations for same person**: "ben.fry@gmail.com" vs "benjamin.fry@yahoo.com"
4. **Email typos**: "john.smith@acme.com" vs "jon.smith@acme.com"
5. **Same person with updated info**: Similar names with one record clearly newer/more complete

For each potential duplicate pair you find, provide:
- contact_id_1: ID of first contact
- contact_id_2: ID of second contact
- confidence: "high", "medium", or "low"
- reasoning: Why you think they're THE SAME PERSON (be specific)

Return your response as a JSON array of duplicate pairs. If no duplicates found, return an empty array.

IMPORTANT: Return ONLY the JSON array, no additional text."""

    # Make Claude API call
    response = claude_client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    # Track costs
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    call_cost = cost_tracker.track_call(
        "claude-3-5-haiku-20241022",
        input_tokens,
        output_tokens,
        phase="duplicate_detection"
    )

    # Parse response
    response_text = response.content[0].text.strip()

    duplicates = []
    try:
        if response_text.startswith('['):
            duplicates = json.loads(response_text)
        else:
            start_idx = response_text.find('[')
            end_idx = response_text.rfind(']') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                duplicates = json.loads(json_str)
    except json.JSONDecodeError as e:
        # Log parse error
        if run:
            run.add_metadata({"parse_error": str(e), "raw_response": response_text[:500]})

    # Add metadata to run
    if run:
        run.add_metadata({
            "duplicates_found": len(duplicates),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "call_cost_usd": round(call_cost, 6),
            "model": "claude-3-5-haiku-20241022"
        })

        # Add output validation
        run.add_outputs({
            "duplicates": duplicates,
            "duplicate_count": len(duplicates),
            "response_valid": isinstance(duplicates, list)
        })

    return {
        "duplicates": duplicates,
        "metadata": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": call_cost,
            "model": "claude-3-5-haiku-20241022"
        }
    }


@traceable(name="validate_emails", tags=["email-validation"])
def traced_email_validation(contacts: List[Dict], activities: Dict) -> Dict[str, Any]:
    """
    Wrapped email validation with LangSmith tracing.
    Tracks validation logic and results.
    """
    run = get_current_run_tree()
    if run:
        run.add_metadata({
            "contact_count": len(contacts),
            "phase": "email_validation"
        })

    # Validation logic
    def format_date(date_str):
        if not date_str:
            return None
        return date_str[:10] if len(date_str) > 10 else date_str

    updates = []
    stats = {'Valid': 0, 'Invalid': 0, 'Unknown': 0}

    for contact in contacts:
        # Check SFDC native bounce fields FIRST
        has_bounced = bool(contact.get('EmailBouncedReason'))
        bounce_date = contact.get('EmailBouncedDate')

        if has_bounced:
            # Email bounced
            update = {
                'Id': contact['Id'],
                'Email_Status__c': 'Invalid',
                'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
                'Email_Verified_Date__c': None
            }
            stats['Invalid'] += 1
        else:
            # Check activity for successful sends
            contact_activities = activities.get(contact['Id'], [])

            successful_sends = []
            for activity in contact_activities:
                status = activity.get('status', '').lower()
                if 'completed' in status or 'sent' in status:
                    successful_sends.append(activity['date'])

            if successful_sends:
                update = {
                    'Id': contact['Id'],
                    'Email_Status__c': 'Valid',
                    'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
                    'Email_Verified_Date__c': format_date(max(successful_sends))
                }
                stats['Valid'] += 1
            else:
                update = {
                    'Id': contact['Id'],
                    'Email_Status__c': 'Unknown',
                    'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
                    'Email_Verified_Date__c': None
                }
                stats['Unknown'] += 1

        # Only update if status changed
        if contact.get('Email_Status__c') != update['Email_Status__c']:
            updates.append(update)

    result = {
        "status": "success",
        "total_processed": len(contacts),
        "updates_needed": len(updates),
        "stats": stats,
        "updates": updates
    }

    # Add outputs
    if run:
        run.add_outputs({
            "stats": result["stats"],
            "updates_needed": result["updates_needed"]
        })

    return result


@traceable(name="mark_duplicates_for_review", tags=["duplicate-marking"])
def traced_duplicate_marking(duplicate_pairs: List[Dict], contacts_dict: Dict) -> Dict[str, Any]:
    """
    Wrapped duplicate marking with LangSmith tracing.
    Tracks marking decisions and justifications.
    """
    run = get_current_run_tree()
    if run:
        run.add_metadata({
            "duplicate_pairs": len(duplicate_pairs),
            "phase": "duplicate_marking"
        })

    # Helper functions
    def determine_canonical_name(contact1, contact2):
        """Determine the best/canonical name for duplicate group"""
        name1 = f"{contact1.get('FirstName', '')} {contact1.get('LastName', '')}".strip()
        name2 = f"{contact2.get('FirstName', '')} {contact2.get('LastName', '')}".strip()

        score1 = len(name1)
        score2 = len(name2)

        if contact1.get('Phone'): score1 += 10
        if contact2.get('Phone'): score2 += 10
        if contact1.get('Title'): score1 += 10
        if contact2.get('Title'): score2 += 10

        return name1 if score1 >= score2 else name2

    def generate_justification(contact, other_contact, is_suggested_delete):
        """Generate narrative justification for duplicate marking"""
        name1 = f"{contact.get('FirstName', '')} {contact.get('LastName', '')}".strip()
        name2 = f"{other_contact.get('FirstName', '')} {other_contact.get('LastName', '')}".strip()

        has_phone = bool(contact.get('Phone'))
        has_title = bool(contact.get('Title'))
        is_bounced = bool(contact.get('EmailBouncedReason'))

        other_has_phone = bool(other_contact.get('Phone'))
        other_has_title = bool(other_contact.get('Title'))

        if is_suggested_delete:
            parts = []

            if name1 != name2:
                if name1.lower() == name2.lower():
                    parts.append(f"Name capitalization differs from '{name2}'")
                else:
                    parts.append(f"Likely typo/variant of '{name2}'")

            missing = []
            if not has_phone and other_has_phone:
                missing.append("phone")
            if not has_title and other_has_title:
                missing.append("title")

            if missing:
                parts.append(f"missing {' and '.join(missing)}")

            if is_bounced:
                parts.append("email bounced")

            if not parts:
                parts.append("less complete than other record")

            justification = "; ".join(parts).capitalize()
        else:
            parts = []

            has_data = []
            if has_phone:
                has_data.append("phone")
            if has_title:
                has_data.append("title")

            if has_data:
                parts.append(f"Has {' and '.join(has_data)}")

            if name1 != name2 and len(name1) > len(name2):
                parts.append("more complete name")

            if not is_bounced:
                parts.append("valid email")

            if not parts:
                parts.append("More complete record")

            justification = "; ".join(parts)

        return justification[:255]

    # Marking logic
    updates = []
    decisions = []

    for pair in duplicate_pairs:
        contact_id_1 = pair['contact_id_1']
        contact_id_2 = pair['contact_id_2']

        contact1 = contacts_dict.get(contact_id_1)
        contact2 = contacts_dict.get(contact_id_2)

        if not contact1 or not contact2:
            continue

        # Determine canonical name
        canonical_name = determine_canonical_name(contact1, contact2)

        # Score contacts for suggested action
        score1 = 0
        score2 = 0

        if contact1.get('Phone'): score1 += 1
        if contact2.get('Phone'): score2 += 1
        if contact1.get('Title'): score1 += 1
        if contact2.get('Title'): score2 += 1
        if contact1.get('EmailBouncedReason'): score1 -= 2
        if contact2.get('EmailBouncedReason'): score2 -= 2

        name1 = f"{contact1.get('FirstName', '')} {contact1.get('LastName', '')}".strip()
        name2 = f"{contact2.get('FirstName', '')} {contact2.get('LastName', '')}".strip()
        if len(name1) > len(name2): score1 += 1
        elif len(name2) > len(name1): score2 += 1

        # Determine suggested actions
        if score1 < score2:
            suggested_action_1 = "Delete"
            suggested_action_2 = "Keep - Not a duplicate"
        elif score2 < score1:
            suggested_action_1 = "Keep - Not a duplicate"
            suggested_action_2 = "Delete"
        else:
            suggested_action_1 = "Merge into other record"
            suggested_action_2 = "Merge into other record"

        # Generate justifications
        justification_1 = generate_justification(
            contact1, contact2,
            is_suggested_delete=(suggested_action_1 == "Delete")
        )
        justification_2 = generate_justification(
            contact2, contact1,
            is_suggested_delete=(suggested_action_2 == "Delete")
        )

        # Create updates
        update1 = {
            'Id': contact_id_1,
            'Email_Status__c': 'Duplicate',
            'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
            'Duplicate_Group_Name__c': canonical_name,
            'Duplicate_Justification__c': justification_1,
            'Suggested_Action__c': suggested_action_1,
            'Duplicate_Reviewed__c': False
        }

        update2 = {
            'Id': contact_id_2,
            'Email_Status__c': 'Duplicate',
            'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
            'Duplicate_Group_Name__c': canonical_name,
            'Duplicate_Justification__c': justification_2,
            'Suggested_Action__c': suggested_action_2,
            'Duplicate_Reviewed__c': False
        }

        updates.extend([update1, update2])

        # Track decision
        decisions.append({
            'account_name': pair.get('account_name', 'Unknown'),
            'confidence': pair['confidence'],
            'reasoning': pair['reasoning'],
            'canonical_name': canonical_name,
            'contact_1': {
                'id': contact_id_1,
                'name': name1,
                'email': contact1.get('Email', ''),
                'phone': contact1.get('Phone', 'N/A'),
                'title': contact1.get('Title', 'N/A'),
                'justification': justification_1,
                'suggested_action': suggested_action_1
            },
            'contact_2': {
                'id': contact_id_2,
                'name': name2,
                'email': contact2.get('Email', ''),
                'phone': contact2.get('Phone', 'N/A'),
                'title': contact2.get('Title', 'N/A'),
                'justification': justification_2,
                'suggested_action': suggested_action_2
            }
        })

    result = {
        "status": "success",
        "total_updates": len(updates),
        "duplicate_groups": len(decisions),
        "updates": updates,
        "decisions": decisions
    }

    # Add outputs with validation
    if run:
        run.add_outputs({
            "total_updates": result["total_updates"],
            "duplicate_groups": result["duplicate_groups"],
            "decisions": result["decisions"][:5]  # Sample of decisions
        })

        # QA validation: Check for potential issues
        qa_issues = []

        for decision in result["decisions"]:
            # Flag if both contacts suggested for deletion (shouldn't happen)
            if (decision["contact_1"]["suggested_action"] == "Delete" and
                decision["contact_2"]["suggested_action"] == "Delete"):
                qa_issues.append({
                    "type": "both_marked_delete",
                    "group": decision["canonical_name"]
                })

        if qa_issues:
            run.add_metadata({"qa_issues": qa_issues})

    return result


@traceable(name="update_salesforce", tags=["sfdc-update"])
def traced_salesforce_update(sf, updates: List[Dict], batch_size: int = 200) -> Dict[str, Any]:
    """
    Wrapped Salesforce update with LangSmith tracing.
    Tracks update success/failure rates.
    """
    run = get_current_run_tree()
    if run:
        run.add_metadata({
            "update_count": len(updates),
            "batch_size": batch_size,
            "phase": "sfdc_update"
        })

    # Update logic
    if not updates:
        return {
            "status": "success",
            "message": "No updates needed",
            "success_count": 0,
            "error_count": 0
        }

    success_count = 0
    errors = []

    print(f"[INFO] Updating {len(updates)} contacts in batches of {batch_size}...")

    try:
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            results = sf.bulk.Contact.update(batch)

            for idx, result in enumerate(results):
                if result['success']:
                    success_count += 1
                else:
                    errors.append({
                        'contact_id': batch[idx]['Id'],
                        'error': result.get('errors', 'Unknown error')
                    })

        print(f"[OK] Successfully updated {success_count} contacts")
        if errors:
            print(f"[WARNING] {len(errors)} errors occurred")

        result = {
            "status": "success" if len(errors) == 0 else "partial",
            "success_count": success_count,
            "error_count": len(errors),
            "errors": errors[:10]  # Limit error details
        }

    except Exception as e:
        result = {
            "status": "error",
            "message": f"Batch update failed: {str(e)}",
            "success_count": success_count,
            "error_count": len(updates) - success_count
        }

    # Add outputs
    if run:
        run.add_outputs({
            "success_count": result["success_count"],
            "error_count": result["error_count"],
            "success_rate": round(result["success_count"] / len(updates), 2) if len(updates) > 0 else 0
        })

        if result["error_count"] > 0:
            run.add_metadata({"errors_sample": result.get("errors", [])[:3]})

    return result


def get_cost_summary():
    """Get current cost tracking summary"""
    return cost_tracker.get_summary()


def save_cost_report(output_dir: str = "reports"):
    """Save cost report to file"""
    import pathlib

    cost_summary = get_cost_summary()
    cost_summary["timestamp"] = datetime.now().isoformat()

    output_path = pathlib.Path(output_dir) / "cost_report.json"
    with open(output_path, 'w') as f:
        json.dump(cost_summary, f, indent=2)

    print(f"[OK] Cost report saved to {output_path}")

    return cost_summary
