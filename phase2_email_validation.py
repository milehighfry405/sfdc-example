"""
PHASE 2: Email Validation & SFDC Update
Validates emails from activities and updates custom fields
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


def load_checkpoint(filename='phase1_extraction.json'):
    """Load data from Phase 1"""
    with open(filename, 'r') as f:
        data = json.load(f)
    print(f"[OK] Loaded checkpoint from {filename}")
    return data


def validate_email_from_activities(contact, activities):
    """Determine email status from SFDC standard bounce fields and activity history"""

    # Helper to format dates
    def format_date(date_str):
        if not date_str:
            return None
        # If it's already a datetime string, extract just the date part
        return date_str[:10] if len(date_str) > 10 else date_str

    # Check SFDC standard bounce fields FIRST (most reliable)
    has_bounced = contact.get('EmailBouncedReason')
    bounce_date = contact.get('EmailBouncedDate')

    if has_bounced:
        # Email has bounced according to SFDC
        return {
            'Email_Status__c': 'Invalid',
            'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
            'Email_Bounced_Date__c': format_date(bounce_date) if bounce_date else datetime.now().strftime('%Y-%m-%d'),
            'Email_Verified_Date__c': None
        }

    # If no bounce, check activity history for successful sends
    contact_id = contact['Id']
    contact_activities = activities.get(contact_id, [])

    if not contact_activities:
        # No bounce and no activity = Unknown
        return {
            'Email_Status__c': 'Unknown',
            'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
            'Email_Bounced_Date__c': None,
            'Email_Verified_Date__c': None
        }

    # Look for successful sends in activities
    successful_sends = []
    for activity in contact_activities:
        status = activity.get('status', '').lower()
        # Completed email tasks = successful send
        if 'completed' in status or 'sent' in status or 'delivered' in status:
            successful_sends.append(activity['date'])

    if successful_sends:
        # Has successful send activity and no bounce
        return {
            'Email_Status__c': 'Valid',
            'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
            'Email_Bounced_Date__c': None,
            'Email_Verified_Date__c': format_date(max(successful_sends))
        }

    # Has activity but can't determine status
    return {
        'Email_Status__c': 'Unknown',
        'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
        'Email_Bounced_Date__c': None,
        'Email_Verified_Date__c': None
    }


def prepare_updates(contacts, activities):
    """Prepare update payloads for all contacts"""
    updates = []

    for contact in contacts:
        validation_result = validate_email_from_activities(contact, activities)

        # Only update if status changed or fields are empty
        current_status = contact.get('Email_Status__c')

        if current_status != validation_result['Email_Status__c'] or not current_status:
            update_payload = {
                'Id': contact['Id'],
                **validation_result
            }
            updates.append(update_payload)

    return updates


def batch_update_contacts(sf, updates, batch_size=200):
    """Update contacts in batches"""
    if not updates:
        print("[INFO] No updates needed")
        return []

    print(f"[INFO] Preparing to update {len(updates)} contacts...")

    success_count = 0
    errors = []

    # Process in batches
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]

        try:
            # Use bulk update
            results = sf.bulk.Contact.update(batch)

            for idx, result in enumerate(results):
                if result['success']:
                    success_count += 1
                else:
                    errors.append({
                        'contact_id': batch[idx]['Id'],
                        'error': result.get('errors', 'Unknown error')
                    })

        except Exception as e:
            print(f"[ERROR] Batch update failed: {e}")
            errors.append({
                'batch': f"{i}-{i+batch_size}",
                'error': str(e)
            })

    print(f"[OK] Successfully updated {success_count} contacts")

    if errors:
        print(f"[WARNING] {len(errors)} errors occurred")

    return errors


def summarize_updates(updates):
    """Show summary of what will be updated"""
    status_counts = {'Valid': 0, 'Invalid': 0, 'Unknown': 0}

    for update in updates:
        status = update.get('Email_Status__c', 'Unknown')
        status_counts[status] = status_counts.get(status, 0) + 1

    print("\n=== Update Summary ===")
    print(f"  Total contacts to update: {len(updates)}")
    print(f"  Valid emails: {status_counts['Valid']}")
    print(f"  Invalid emails: {status_counts['Invalid']}")
    print(f"  Unknown emails: {status_counts['Unknown']}")

    # Show sample
    print("\n  Sample updates:")
    for update in updates[:3]:
        print(f"    - {update['Id']}: {update['Email_Status__c']}")


if __name__ == '__main__':
    print("=== PHASE 2: Email Validation & Update ===\n")

    # Load Phase 1 data
    checkpoint_data = load_checkpoint()
    contacts = checkpoint_data['contacts']
    activities = checkpoint_data['activities']

    # Prepare updates
    print("\nValidating emails from activities...")
    updates = prepare_updates(contacts, activities)

    if not updates:
        print("[INFO] All contacts already have valid email status")
        exit(0)

    # Show summary
    summarize_updates(updates)

    # Auto-proceed (remove for interactive mode)
    print("\nProceeding with update...")

    # Connect and update
    sf = connect_to_salesforce()
    if not sf:
        exit(1)

    errors = batch_update_contacts(sf, updates)

    # Save results
    result_data = {
        'updates': updates,
        'errors': errors,
        'timestamp': datetime.now().isoformat()
    }

    with open('phase2_update_results.json', 'w') as f:
        json.dump(result_data, f, indent=2, default=str)

    print("\n[OK] Phase 2 complete!")
    print(f"  Updated: {len(updates) - len(errors)} contacts")
    print(f"  Errors: {len(errors)}")
    print("  Results saved to phase2_update_results.json")
