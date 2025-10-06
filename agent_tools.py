"""
SFDC Deduplication Agent Tools
Refactored tools from phase scripts for use with Claude Agent SDK
Integrated with LangSmith for observability
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from simple_salesforce import Salesforce
from dotenv import load_dotenv
from langsmith_wrapper import (
    traced_duplicate_detection,
    traced_email_validation,
    traced_duplicate_marking,
    traced_salesforce_update
)

# Load environment variables
load_dotenv()


# ============================================================================
# TOOL 1: Connect to Salesforce
# ============================================================================

def connect_to_salesforce():
    """
    Connect to Salesforce using credentials from environment variables.

    Returns:
        dict: Connection status and Salesforce connection object
    """
    try:
        sf = Salesforce(
            username=os.getenv('SF_USERNAME'),
            password=os.getenv('SF_PASSWORD'),
            security_token=os.getenv('SF_SECURITY_TOKEN')
        )

        return {
            "status": "success",
            "message": "Connected to Salesforce successfully",
            "connection": sf
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Connection failed: {str(e)}",
            "connection": None
        }


# ============================================================================
# TOOL 2: Extract Contacts (with Account Owner grouping)
# ============================================================================

def extract_contacts(sf, batch_size=None, owner_filter=None):
    """
    Extract contacts from Salesforce grouped by Account Owner.

    Args:
        sf: Salesforce connection object
        batch_size: Optional limit on number of contacts
        owner_filter: Optional list of OwnerId to filter by

    Returns:
        dict: Contacts grouped by OwnerId with metadata
    """
    # Build query with Account Owner field
    query = """
        SELECT Id, FirstName, LastName, Email, Phone, MobilePhone, Title,
               AccountId, Account.Name, Account.OwnerId, Account.Owner.Name,
               OwnerId, Owner.Name, LastModifiedDate,
               Email_Status__c, email_last_updated_date__c,
               Email_Verified_Date__c,
               EmailBouncedReason, EmailBouncedDate, IsEmailBounced
        FROM Contact
        WHERE AccountId != NULL
    """

    if owner_filter:
        owner_list = "','".join(owner_filter)
        query += f" AND Account.OwnerId IN ('{owner_list}')"

    query += " ORDER BY Account.OwnerId, Account.Name, LastName, FirstName"

    if batch_size:
        query += f" LIMIT {batch_size}"

    try:
        result = sf.query(query)
        contacts = result['records']

        print(f"[OK] Retrieved {len(contacts)} contacts")

        # Clean up nested fields
        for contact in contacts:
            # Extract Account info
            if contact.get('Account'):
                contact['AccountName'] = contact['Account'].get('Name', '')
                contact['AccountOwnerId'] = contact['Account'].get('OwnerId', '')
                if contact['Account'].get('Owner'):
                    contact['AccountOwnerName'] = contact['Account']['Owner'].get('Name', '')
                del contact['Account']

            # Extract Contact Owner info
            if contact.get('Owner'):
                contact['OwnerName'] = contact['Owner'].get('Name', '')
                del contact['Owner']

        # Group by Account Owner
        grouped_by_owner = defaultdict(list)
        for contact in contacts:
            owner_id = contact.get('AccountOwnerId', 'NO_OWNER')
            grouped_by_owner[owner_id].append(contact)

        # Create owner metadata
        owner_metadata = {}
        for owner_id, owner_contacts in grouped_by_owner.items():
            first_contact = owner_contacts[0]
            owner_metadata[owner_id] = {
                'owner_name': first_contact.get('AccountOwnerName', 'Unknown'),
                'contact_count': len(owner_contacts),
                'accounts': list(set(c.get('AccountName', '') for c in owner_contacts))
            }

        return {
            "status": "success",
            "total_contacts": len(contacts),
            "owner_count": len(grouped_by_owner),
            "contacts_by_owner": dict(grouped_by_owner),
            "owner_metadata": owner_metadata,
            "all_contacts": contacts
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Contact extraction failed: {str(e)}",
            "total_contacts": 0
        }


# ============================================================================
# TOOL 3: Extract Email Activities
# ============================================================================

def extract_email_activities(sf, contact_ids, days_back=90):
    """
    Extract email activity data for contacts.

    Args:
        sf: Salesforce connection object
        contact_ids: List of contact IDs to query
        days_back: Number of days of history to pull

    Returns:
        dict: Email activities by contact ID
    """
    if not contact_ids:
        return {}

    # Convert to comma-separated string
    id_list = "','".join(contact_ids)

    # Query Task objects for email tasks
    task_query = f"""
        SELECT Id, WhoId, Subject, Status, ActivityDate, CreatedDate,
               TaskSubtype, Description
        FROM Task
        WHERE WhoId IN ('{id_list}')
        AND TaskSubtype = 'Email'
        ORDER BY CreatedDate DESC
        LIMIT 10000
    """

    activities = defaultdict(list)

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
        print(f"  Task query failed: {str(e)[:100]}")

    return dict(activities)


# ============================================================================
# TOOL 4: Validate Emails (with LangSmith tracing)
# ============================================================================

def validate_emails(contacts, activities):
    """
    Validate email addresses based on SFDC bounce data and activity.
    Uses LangSmith tracing wrapper for observability.

    Args:
        contacts: List of contact records
        activities: Email activity data by contact ID

    Returns:
        dict: Validation results and update payloads
    """
    return traced_email_validation(contacts, activities)


# ============================================================================
# TOOL 5: Detect Duplicates (with LangSmith tracing)
# ============================================================================

def detect_duplicates_for_owner(owner_id, owner_contacts, claude_client):
    """
    Detect duplicates within a single account owner's contacts.
    Uses LangSmith tracing wrapper for observability and cost tracking.

    Args:
        owner_id: Account Owner ID
        owner_contacts: List of contacts for this owner
        claude_client: Anthropic client for AI analysis

    Returns:
        dict: Duplicate pairs detected for this owner
    """
    # Group by account first
    contacts_by_account = defaultdict(list)
    for contact in owner_contacts:
        account_id = contact.get('AccountId', 'NO_ACCOUNT')
        contacts_by_account[account_id].append(contact)

    all_duplicates = []

    # Analyze each account
    for account_id, account_contacts in contacts_by_account.items():
        if len(account_contacts) < 2:
            continue

        account_name = account_contacts[0].get('AccountName', 'Unknown')
        owner_name = account_contacts[0].get('AccountOwnerName', 'Unknown')

        # Format for Claude
        formatted_contacts = []
        for c in account_contacts:
            formatted_contacts.append({
                'Id': c['Id'],
                'Name': f"{c.get('FirstName', '')} {c.get('LastName', '')}".strip(),
                'Email': c.get('Email', ''),
                'Phone': c.get('Phone', ''),
                'MobilePhone': c.get('MobilePhone', ''),
                'Title': c.get('Title', ''),
                'LastModified': c.get('LastModifiedDate', '')
            })

        try:
            # Call traced version
            result = traced_duplicate_detection(
                owner_id=owner_id,
                owner_name=owner_name,
                formatted_contacts=formatted_contacts,
                claude_client=claude_client,
                account_name=account_name
            )

            duplicates = result.get('duplicates', [])

            # Add account context to each duplicate
            for dup in duplicates:
                dup['account_id'] = account_id
                dup['account_name'] = account_name

            all_duplicates.extend(duplicates)

        except Exception as e:
            print(f"[ERROR] Claude API failed for {account_name}: {e}")
            continue

    return {
        "status": "success",
        "owner_id": owner_id,
        "duplicate_pairs": all_duplicates,
        "total_pairs": len(all_duplicates)
    }


# ============================================================================
# HELPER FUNCTIONS (used by tools)
# ============================================================================

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


# ============================================================================
# TOOL 6: Mark Duplicates for Review (with LangSmith tracing)
# ============================================================================

def mark_duplicates_for_review(duplicate_pairs, contacts_dict):
    """
    Prepare update payloads to mark both contacts in duplicate pairs.
    Uses LangSmith tracing wrapper for QA validation.

    Args:
        duplicate_pairs: List of detected duplicate pairs
        contacts_dict: Contact lookup by ID

    Returns:
        dict: Update payloads and decisions
    """
    return traced_duplicate_marking(duplicate_pairs, contacts_dict)


# ============================================================================
# TOOL 7: Update Salesforce (with LangSmith tracing)
# ============================================================================

def update_salesforce_contacts(sf, updates, batch_size=200):
    """
    Batch update contacts in Salesforce.
    Uses LangSmith tracing wrapper for success rate monitoring.

    Args:
        sf: Salesforce connection object
        updates: List of contact update payloads
        batch_size: Records per batch

    Returns:
        dict: Success/error counts
    """
    return traced_salesforce_update(sf, updates, batch_size)
