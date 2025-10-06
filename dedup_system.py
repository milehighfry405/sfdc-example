"""
AI-Powered Contact Deduplication & Email Validation System
Extracts SFDC contacts, validates emails from activities, detects duplicates using Claude AI
"""

from simple_salesforce import Salesforce
import json
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from collections import defaultdict

# Load credentials
load_dotenv()

SF_USERNAME = os.getenv('SF_USERNAME')
SF_PASSWORD = os.getenv('SF_PASSWORD')
SF_SECURITY_TOKEN = os.getenv('SF_SECURITY_TOKEN')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')


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


def extract_contacts(sf):
    """Extract contacts with custom fields and Account data"""
    query = """
        SELECT Id, FirstName, LastName, Email, Phone, MobilePhone, Title,
               AccountId, Account.Name, LastModifiedDate,
               Email_Status__c, email_last_updated_date__c,
               Email_Bounced_Date__c, Email_Verified_Date__c,
               EmailBouncedReason, EmailBouncedDate
        FROM Contact
        WHERE AccountId != NULL
        ORDER BY Account.Name, LastName, FirstName
    """

    try:
        result = sf.query(query)
        contacts = result['records']
        print(f"[OK] Retrieved {len(contacts)} contacts")

        # Clean up nested Account field
        for contact in contacts:
            if contact.get('Account'):
                contact['AccountName'] = contact['Account']['Name']
                del contact['Account']
            else:
                contact['AccountName'] = 'No Account'

        return contacts
    except Exception as e:
        print(f"[ERROR] Query failed: {e}")
        return []


def extract_email_activities(sf, contact_ids, days_back=90):
    """Extract email activity data for contacts (last N days)"""

    # Simplified queries without date filter (can add back if needed)
    # Convert contact IDs to comma-separated string for SOQL IN clause
    id_list = "','".join(contact_ids)

    # Query EmailMessage objects (if org has email tracking enabled)
    email_query = f"""
        SELECT Id, RelatedToId, Status, CreatedDate, MessageDate,
               HasAttachment, Incoming, Subject
        FROM EmailMessage
        WHERE RelatedToId IN ('{id_list}')
        ORDER BY CreatedDate DESC
        LIMIT 1000
    """

    # Query Task objects for email tasks
    task_query = f"""
        SELECT Id, WhoId, Subject, Status, ActivityDate, CreatedDate,
               TaskSubtype, Description
        FROM Task
        WHERE WhoId IN ('{id_list}')
        AND TaskSubtype = 'Email'
        ORDER BY CreatedDate DESC
        LIMIT 1000
    """

    activities = defaultdict(list)

    # Try EmailMessage first
    try:
        result = sf.query(email_query)
        if result['totalSize'] > 0:
            print(f"[OK] Found {result['totalSize']} EmailMessage records")
            for record in result['records']:
                contact_id = record['RelatedToId']
                activities[contact_id].append({
                    'type': 'EmailMessage',
                    'status': record.get('Status'),
                    'date': record.get('MessageDate') or record.get('CreatedDate'),
                    'subject': record.get('Subject')
                })
        else:
            print("  No EmailMessage records found")
    except Exception as e:
        print(f"  EmailMessage query skipped: {str(e)[:100]}")

    # Try Task objects
    try:
        result = sf.query(task_query)
        if result['totalSize'] > 0:
            print(f"[OK] Found {result['totalSize']} email Task records")
            for record in result['records']:
                contact_id = record['WhoId']
                activities[contact_id].append({
                    'type': 'Task',
                    'status': record.get('Status'),
                    'date': record.get('CreatedDate'),
                    'subject': record.get('Subject'),
                    'description': record.get('Description', '')
                })
        else:
            print("  No email Task records found")
    except Exception as e:
        print(f"  Task query skipped: {str(e)[:100]}")

    return dict(activities)


def validate_email_from_activities(contact, activities):
    """Determine email status based on activity history"""

    contact_id = contact['Id']
    contact_activities = activities.get(contact_id, [])

    if not contact_activities:
        return {
            'Email_Status__c': 'Unknown',
            'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
            'Email_Bounced_Date__c': None,
            'Email_Verified_Date__c': None
        }

    # Look for bounces and successful sends
    bounces = []
    successful_sends = []

    for activity in contact_activities:
        status = activity.get('status', '').lower()
        description = activity.get('description', '').lower()

        # Check for bounce indicators
        if any(keyword in status or keyword in description
               for keyword in ['bounce', 'failed', 'undeliverable', 'invalid']):
            bounces.append(activity['date'])

        # Check for successful sends
        elif any(keyword in status
                for keyword in ['sent', 'delivered', 'completed']):
            successful_sends.append(activity['date'])

    # Determine status (most recent activity wins)
    if bounces and successful_sends:
        # Compare most recent dates
        latest_bounce = max(bounces)
        latest_success = max(successful_sends)

        if latest_bounce > latest_success:
            email_status = 'Invalid'
        else:
            email_status = 'Valid'
    elif bounces:
        email_status = 'Invalid'
    elif successful_sends:
        email_status = 'Valid'
    else:
        email_status = 'Unknown'

    return {
        'Email_Status__c': email_status,
        'email_last_updated_date__c': datetime.now().strftime('%Y-%m-%d'),
        'Email_Bounced_Date__c': max(bounces) if bounces else None,
        'Email_Verified_Date__c': max(successful_sends) if successful_sends else None
    }


def group_contacts_by_account(contacts):
    """Group contacts by AccountId"""
    grouped = defaultdict(list)

    for contact in contacts:
        account_id = contact.get('AccountId', 'NO_ACCOUNT')
        grouped[account_id].append(contact)

    print(f"[OK] Grouped contacts into {len(grouped)} accounts")

    # Show distribution
    for account_id, account_contacts in list(grouped.items())[:5]:
        account_name = account_contacts[0].get('AccountName', 'Unknown')
        print(f"  {account_name}: {len(account_contacts)} contacts")

    return dict(grouped)


def save_checkpoint(data, filename):
    """Save intermediate data"""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    print(f"[OK] Saved checkpoint to {filename}")


if __name__ == '__main__':
    print("=== PHASE 1: Data Extraction ===\n")

    # Connect
    sf = connect_to_salesforce()
    if not sf:
        exit(1)

    # Extract contacts
    contacts = extract_contacts(sf)
    if not contacts:
        print("No contacts found")
        exit(1)

    # Extract activities
    print("\nExtracting email activities...")
    contact_ids = [c['Id'] for c in contacts]
    activities = extract_email_activities(sf, contact_ids)

    # Group by account
    print("\nGrouping contacts by account...")
    grouped_contacts = group_contacts_by_account(contacts)

    # Save checkpoint
    checkpoint_data = {
        'contacts': contacts,
        'activities': activities,
        'grouped_contacts': {
            account_id: [c['Id'] for c in contacts_list]
            for account_id, contacts_list in grouped_contacts.items()
        }
    }
    save_checkpoint(checkpoint_data, 'phase1_extraction.json')

    print("\n[OK] Phase 1 complete! Data extracted and grouped.")
    print(f"  Total contacts: {len(contacts)}")
    print(f"  Contacts with activity: {len(activities)}")
    print(f"  Accounts: {len(grouped_contacts)}")
