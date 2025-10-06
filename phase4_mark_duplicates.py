"""
PHASE 4: Mark Duplicates in SFDC
Updates Email_Status__c = 'Duplicate' for detected duplicate contacts
"""

from simple_salesforce import Salesforce
import json
import os
from dotenv import load_dotenv
from datetime import datetime

# Load credentials
load_dotenv()

SF_USERNAME = os.getenv('SF_USERNAME')
SF_PASSWORD = os.getenv('SF_PASSWORD')
SF_SECURITY_TOKEN = os.getenv('SF_SECURITY_TOKEN')


def connect_to_salesforce():
    """Connect to Salesforce"""
    try:
        sf = Salesforce(
            username=SF_USERNAME,
            password=SF_PASSWORD,
            security_token=SF_SECURITY_TOKEN
        )
        print("[OK] Connected to Salesforce")
        return sf
    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        return None


def load_duplicates(filename='phase3_duplicates.json'):
    """Load duplicate detection results"""
    with open(filename, 'r') as f:
        data = json.load(f)
    print(f"[OK] Loaded duplicates from {filename}")
    return data


def load_contacts(filename='phase1_extraction.json'):
    """Load contact data"""
    with open(filename, 'r') as f:
        data = json.load(f)
    return {c['Id']: c for c in data['contacts']}


def determine_canonical_name(contact1, contact2):
    """
    Determine the canonical/best name for the duplicate group
    Strategy: Pick the more complete name (prefer longer, more formal version)

    Returns: canonical name string
    """
    name1 = f"{contact1.get('FirstName', '')} {contact1.get('LastName', '')}".strip()
    name2 = f"{contact2.get('FirstName', '')} {contact2.get('LastName', '')}".strip()

    # Score each name
    score1 = 0
    score2 = 0

    # Prefer longer names (e.g., "Benjamin" over "Ben")
    score1 += len(name1)
    score2 += len(name2)

    # Prefer names with more data completeness
    if contact1.get('Phone'): score1 += 10
    if contact2.get('Phone'): score2 += 10

    if contact1.get('Title'): score1 += 10
    if contact2.get('Title'): score2 += 10

    # Return the name with higher score
    return name1 if score1 >= score2 else name2


def generate_justification(contact, other_contact, is_suggested_delete):
    """Generate a narrative justification explaining why this is likely a duplicate"""

    # Extract names for comparison
    name1 = f"{contact.get('FirstName', '')} {contact.get('LastName', '')}".strip()
    name2 = f"{other_contact.get('FirstName', '')} {other_contact.get('LastName', '')}".strip()

    # Check data completeness
    has_phone = bool(contact.get('Phone'))
    has_title = bool(contact.get('Title'))
    is_bounced = bool(contact.get('EmailBouncedReason'))

    other_has_phone = bool(other_contact.get('Phone'))
    other_has_title = bool(other_contact.get('Title'))

    # Build narrative justification
    if is_suggested_delete:
        # Explain why THIS record should be deleted
        parts = []

        # Name analysis
        if name1 != name2:
            if name1.lower() == name2.lower():
                parts.append(f"Name capitalization differs from '{name2}'")
            else:
                parts.append(f"Likely typo/variant of '{name2}'")

        # Data completeness
        missing = []
        if not has_phone and other_has_phone:
            missing.append("phone")
        if not has_title and other_has_title:
            missing.append("title")

        if missing:
            parts.append(f"missing {' and '.join(missing)}")

        # Email issues
        if is_bounced:
            parts.append("email bounced")

        if not parts:
            parts.append("less complete than other record")

        justification = "; ".join(parts).capitalize()

    else:
        # Explain why THIS record should be KEPT
        parts = []

        # Data completeness
        has_data = []
        if has_phone:
            has_data.append("phone")
        if has_title:
            has_data.append("title")

        if has_data:
            parts.append(f"Has {' and '.join(has_data)}")

        # Name quality
        if name1 != name2 and len(name1) > len(name2):
            parts.append("more complete name")

        # Email quality
        if not is_bounced:
            parts.append("valid email")

        if not parts:
            parts.append("More complete record")

        justification = "; ".join(parts)

    return justification[:255]  # Truncate to field limit


def prepare_duplicate_updates(duplicates_data, contacts_dict):
    """Prepare update payloads to mark BOTH contacts in duplicate pairs"""
    updates = []
    decisions = []

    for account_id, data in duplicates_data['duplicates_by_account'].items():
        account_name = data['account_name']

        for pair in data['duplicates']:
            contact_id_1 = pair['contact_id_1']
            contact_id_2 = pair['contact_id_2']

            contact1 = contacts_dict.get(contact_id_1)
            contact2 = contacts_dict.get(contact_id_2)

            if not contact1 or not contact2:
                print(f"[WARNING] Could not find contacts for pair: {contact_id_1}, {contact_id_2}")
                continue

            # Determine canonical name for the group
            canonical_name = determine_canonical_name(contact1, contact2)

            # Score contacts to determine which to suggest deleting
            score1 = 0
            score2 = 0

            # Data completeness scoring
            if contact1.get('Phone'): score1 += 1
            if contact2.get('Phone'): score2 += 1
            if contact1.get('MobilePhone'): score1 += 1
            if contact2.get('MobilePhone'): score2 += 1
            if contact1.get('Title'): score1 += 1
            if contact2.get('Title'): score2 += 1

            # Email bounce penalty
            if contact1.get('EmailBouncedReason'): score1 -= 2
            if contact2.get('EmailBouncedReason'): score2 -= 2

            # Name length (prefer longer/more formal)
            name1 = f"{contact1.get('FirstName', '')} {contact1.get('LastName', '')}".strip()
            name2 = f"{contact2.get('FirstName', '')} {contact2.get('LastName', '')}".strip()
            if len(name1) > len(name2): score1 += 1
            elif len(name2) > len(name1): score2 += 1

            # Determine suggested actions
            if score1 < score2:
                # Contact 1 is less complete - suggest delete
                suggested_action_1 = "Delete"
                suggested_action_2 = "Keep - Not a duplicate"
            elif score2 < score1:
                # Contact 2 is less complete - suggest delete
                suggested_action_1 = "Keep - Not a duplicate"
                suggested_action_2 = "Delete"
            else:
                # Equal - suggest merge
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

            # Mark BOTH contacts as duplicates with review fields
            update_payload_1 = {
                'Id': contact_id_1,
                'Email_Status__c': 'Duplicate',
                'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
                'Duplicate_Group_Name__c': canonical_name,
                'Duplicate_Justification__c': justification_1,
                'Suggested_Action__c': suggested_action_1,
                'Duplicate_Reviewed__c': False
            }

            update_payload_2 = {
                'Id': contact_id_2,
                'Email_Status__c': 'Duplicate',
                'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
                'Duplicate_Group_Name__c': canonical_name,
                'Duplicate_Justification__c': justification_2,
                'Suggested_Action__c': suggested_action_2,
                'Duplicate_Reviewed__c': False
            }

            updates.append(update_payload_1)
            updates.append(update_payload_2)

            # Track decision
            name1 = f"{contact1.get('FirstName', '')} {contact1.get('LastName', '')}".strip()
            name2 = f"{contact2.get('FirstName', '')} {contact2.get('LastName', '')}".strip()

            decisions.append({
                'account': account_name,
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

    return updates, decisions


def batch_update_contacts(sf, updates):
    """Update contacts in batches"""
    if not updates:
        print("[INFO] No updates needed")
        return []

    print(f"[INFO] Preparing to mark {len(updates)} contacts as duplicates...")

    success_count = 0
    errors = []

    try:
        results = sf.bulk.Contact.update(updates)

        for idx, result in enumerate(results):
            if result['success']:
                success_count += 1
            else:
                errors.append({
                    'contact_id': updates[idx]['Id'],
                    'error': result.get('errors', 'Unknown error')
                })

    except Exception as e:
        print(f"[ERROR] Batch update failed: {e}")
        errors.append({'error': str(e)})

    print(f"[OK] Successfully marked {success_count} contacts as duplicates")

    if errors:
        print(f"[WARNING] {len(errors)} errors occurred")

    return errors


def display_decisions(decisions):
    """Show what will be marked as duplicate"""
    print("\n=== Duplicate Marking Decisions ===\n")

    for idx, decision in enumerate(decisions, 1):
        print(f"{idx}. {decision['account']} - {decision['confidence'].upper()} confidence")
        print(f"   Group Name: {decision['canonical_name']}")
        print(f"   AI Reasoning: {decision['reasoning']}")
        print(f"   ")
        print(f"   BOTH CONTACTS WILL BE MARKED AS DUPLICATES FOR REVIEW:")
        print(f"   ")
        print(f"   Contact A:")
        print(f"      Name: {decision['contact_1']['name']}")
        print(f"      Email: {decision['contact_1']['email']}")
        print(f"      Phone: {decision['contact_1']['phone']}")
        print(f"      Title: {decision['contact_1']['title']}")
        print(f"      Justification: {decision['contact_1']['justification']}")
        print(f"      Suggested Action: {decision['contact_1']['suggested_action']}")
        print(f"      ID: {decision['contact_1']['id']}")
        print(f"   ")
        print(f"   Contact B:")
        print(f"      Name: {decision['contact_2']['name']}")
        print(f"      Email: {decision['contact_2']['email']}")
        print(f"      Phone: {decision['contact_2']['phone']}")
        print(f"      Title: {decision['contact_2']['title']}")
        print(f"      Justification: {decision['contact_2']['justification']}")
        print(f"      Suggested Action: {decision['contact_2']['suggested_action']}")
        print(f"      ID: {decision['contact_2']['id']}")
        print(f"")


if __name__ == '__main__':
    print("=== PHASE 4: Mark Duplicates ===\n")

    # Load data
    duplicates_data = load_duplicates()
    contacts_dict = load_contacts()

    if duplicates_data['total_pairs'] == 0:
        print("[INFO] No duplicates found to mark")
        exit(0)

    # Prepare updates
    updates, decisions = prepare_duplicate_updates(duplicates_data, contacts_dict)

    # Display decisions
    display_decisions(decisions)

    # Auto-proceed
    print("Proceeding with updates...\n")

    # Connect and update
    sf = connect_to_salesforce()
    if not sf:
        exit(1)

    errors = batch_update_contacts(sf, updates)

    # Save results
    result_data = {
        'decisions': decisions,
        'updates': updates,
        'errors': errors,
        'timestamp': datetime.now().isoformat()
    }

    with open('phase4_duplicate_marking.json', 'w') as f:
        json.dump(result_data, f, indent=2, default=str)

    print("\n[OK] Phase 4 complete!")
    print(f"  Contacts marked as duplicates: {len(updates) - len(errors)}")
    print(f"  Duplicate groups created: {len(decisions)}")
    print(f"  Errors: {len(errors)}")
    print("  Results saved to phase4_duplicate_marking.json")
    print("\n  Next steps:")
    print("  - Create SFDC report: Filter by Email_Status__c = 'Duplicate'")
    print("  - Group by: Duplicate_Group_Name__c")
    print("  - Subscribe account owners to review and merge/delete")
