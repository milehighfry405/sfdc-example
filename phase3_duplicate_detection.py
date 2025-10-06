"""
PHASE 3: Duplicate Detection using Claude AI
Detects potential duplicates within each account
"""

import json
import os
from dotenv import load_dotenv
from anthropic import Anthropic
from collections import defaultdict

# Load credentials
load_dotenv()
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')


def load_checkpoint(filename='phase1_extraction.json'):
    """Load data from Phase 1"""
    with open(filename, 'r') as f:
        data = json.load(f)
    print(f"[OK] Loaded checkpoint from {filename}")
    return data


def group_contacts_by_account(contacts):
    """Group contacts by AccountId"""
    grouped = defaultdict(list)

    for contact in contacts:
        account_id = contact.get('AccountId', 'NO_ACCOUNT')
        grouped[account_id].append(contact)

    return dict(grouped)


def format_contact_for_comparison(contact):
    """Format contact data for Claude"""
    return {
        'Id': contact['Id'],
        'Name': f"{contact.get('FirstName', '')} {contact.get('LastName', '')}".strip(),
        'Email': contact.get('Email', ''),
        'Phone': contact.get('Phone', ''),
        'MobilePhone': contact.get('MobilePhone', ''),
        'Title': contact.get('Title', ''),
        'LastModified': contact.get('LastModifiedDate', '')
    }


def detect_duplicates_in_account(account_name, contacts, client):
    """Use Claude to detect duplicates within an account"""

    if len(contacts) < 2:
        return []  # No duplicates possible with < 2 contacts

    # Format contacts for Claude
    formatted_contacts = [format_contact_for_comparison(c) for c in contacts]

    prompt = f"""You are analyzing contacts from the Salesforce account "{account_name}" to identify DUPLICATE RECORDS OF THE SAME PERSON.

Here are the contacts:

{json.dumps(formatted_contacts, indent=2)}

CRITICAL: Only flag contacts as duplicates if they are likely THE SAME PERSON with multiple records.

DO NOT flag as duplicates:
- Different people who work at the same company
- Different people who share a company phone number
- Colleagues with different names, emails, and titles

DO flag as duplicates if you see:
1. **Name variations of same person**: "Ben Fry" vs "Benjamin Fry", "Bob Smith" vs "Robert Smith", "Jon" vs "Jonathan"
2. **Name typos**: "Ben Fry" vs "Ben Frye" (especially if titles/roles are similar)
3. **Email variations for same person**: "ben.fry@gmail.com" vs "benjamin.fry@yahoo.com" (same person, different emails)
4. **Email typos**: "john.smith@acme.com" vs "jon.smith@acme.com" (likely typo in first name)
5. **Same person with updated info**: Similar names with one record clearly newer/more complete

For each potential duplicate pair you find, provide:
- contact_id_1: ID of first contact
- contact_id_2: ID of second contact
- confidence: "high", "medium", or "low"
- reasoning: Why you think they're THE SAME PERSON (be specific)

Return your response as a JSON array of duplicate pairs. If no duplicates found, return an empty array.

Example of VALID duplicate:
[
  {{
    "contact_id_1": "003xxx1",
    "contact_id_2": "003xxx2",
    "confidence": "high",
    "reasoning": "Same last name (Fry), first name variation (Ben vs Benjamin), similar email patterns (ben.fry vs benjamin.fry). Likely the same person with two email addresses."
  }}
]

IMPORTANT: Return ONLY the JSON array, no additional text."""

    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse Claude's response
        response_text = response.content[0].text.strip()

        # Try to extract JSON from response
        if response_text.startswith('['):
            duplicates = json.loads(response_text)
        else:
            # Try to find JSON in the response
            start_idx = response_text.find('[')
            end_idx = response_text.rfind(']') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                duplicates = json.loads(json_str)
            else:
                duplicates = []

        return duplicates

    except Exception as e:
        print(f"[ERROR] Claude API call failed for {account_name}: {e}")
        return []


def analyze_all_accounts(grouped_contacts, client):
    """Analyze each account for duplicates"""

    all_duplicates = {}
    total_pairs = 0

    print("\n=== Analyzing Accounts for Duplicates ===\n")

    for account_id, contacts in grouped_contacts.items():
        account_name = contacts[0].get('AccountName', 'Unknown')

        if len(contacts) < 2:
            print(f"  {account_name}: Only 1 contact, skipping")
            continue

        print(f"  Analyzing {account_name} ({len(contacts)} contacts)...")

        duplicates = detect_duplicates_in_account(account_name, contacts, client)

        if duplicates:
            all_duplicates[account_id] = {
                'account_name': account_name,
                'duplicates': duplicates
            }
            total_pairs += len(duplicates)
            print(f"    Found {len(duplicates)} potential duplicate pair(s)")
        else:
            print(f"    No duplicates found")

    print(f"\n[OK] Analysis complete: {total_pairs} total duplicate pairs found")

    return all_duplicates


def generate_slack_report(all_duplicates, contacts_dict):
    """Generate Slack-ready markdown report"""

    report = []

    report.append("# Contact Deduplication Report")
    report.append(f"Generated: {json.dumps(None, default=str)}")
    report.append("")

    if not all_duplicates:
        report.append("No duplicate contacts found.")
        return "\n".join(report)

    total_pairs = sum(len(data['duplicates']) for data in all_duplicates.values())
    report.append(f"**Total Duplicate Pairs Found: {total_pairs}**")
    report.append("")

    # Group by account
    for account_id, data in all_duplicates.items():
        account_name = data['account_name']
        duplicates = data['duplicates']

        report.append(f"## {account_name}")
        report.append("")

        for idx, pair in enumerate(duplicates, 1):
            contact1 = contacts_dict.get(pair['contact_id_1'], {})
            contact2 = contacts_dict.get(pair['contact_id_2'], {})

            report.append(f"### Duplicate Pair #{idx} - {pair['confidence'].upper()} Confidence")
            report.append("")

            # Side by side comparison
            report.append("| Field | Contact A | Contact B |")
            report.append("|-------|-----------|-----------|")
            report.append(f"| **Name** | {contact1.get('FirstName', '')} {contact1.get('LastName', '')} | {contact2.get('FirstName', '')} {contact2.get('LastName', '')} |")
            report.append(f"| **Email** | {contact1.get('Email', 'N/A')} | {contact2.get('Email', 'N/A')} |")
            report.append(f"| **Phone** | {contact1.get('Phone', 'N/A')} | {contact2.get('Phone', 'N/A')} |")
            report.append(f"| **Mobile** | {contact1.get('MobilePhone', 'N/A')} | {contact2.get('MobilePhone', 'N/A')} |")
            report.append(f"| **Title** | {contact1.get('Title', 'N/A')} | {contact2.get('Title', 'N/A')} |")
            report.append(f"| **Last Modified** | {contact1.get('LastModifiedDate', 'N/A')} | {contact2.get('LastModifiedDate', 'N/A')} |")
            report.append(f"| **SFDC ID** | `{pair['contact_id_1']}` | `{pair['contact_id_2']}` |")
            report.append("")

            report.append(f"**Why this is a duplicate:** {pair['reasoning']}")
            report.append("")

            report.append("**Action Required:**")
            report.append("- Review both contacts")
            report.append("- Reply with which contact ID to KEEP")
            report.append("- The other will be marked as Email_Status__c = 'Duplicate'")
            report.append("")
            report.append("---")
            report.append("")

    return "\n".join(report)


if __name__ == '__main__':
    print("=== PHASE 3: Duplicate Detection ===\n")

    # Check API key
    if not ANTHROPIC_API_KEY:
        print("[ERROR] ANTHROPIC_API_KEY not found in .env file")
        print("Please add your Claude API key to continue")
        exit(1)

    # Load data
    checkpoint_data = load_checkpoint()
    contacts = checkpoint_data['contacts']

    # Create lookup dict
    contacts_dict = {c['Id']: c for c in contacts}

    # Group by account
    grouped_contacts = group_contacts_by_account(contacts)
    print(f"[OK] Grouped {len(contacts)} contacts into {len(grouped_contacts)} accounts")

    # Initialize Claude client
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    print("[OK] Claude API client initialized")

    # Analyze for duplicates
    all_duplicates = analyze_all_accounts(grouped_contacts, client)

    # Generate report
    print("\nGenerating Slack-ready report...")
    slack_report = generate_slack_report(all_duplicates, contacts_dict)

    # Save results
    results = {
        'duplicates_by_account': all_duplicates,
        'total_pairs': sum(len(data['duplicates']) for data in all_duplicates.values()),
        'timestamp': None  # Will be serialized as string
    }

    with open('phase3_duplicates.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)

    with open('phase3_slack_report.md', 'w') as f:
        f.write(slack_report)

    print("[OK] Results saved to:")
    print("  - phase3_duplicates.json (structured data)")
    print("  - phase3_slack_report.md (Slack-ready report)")

    print("\n[OK] Phase 3 complete!")
    print(f"  Total duplicate pairs: {results['total_pairs']}")
