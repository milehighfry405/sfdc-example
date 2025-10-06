"""
Salesforce Contact Deduplication POC
Connects to SFDC and pulls contact data for duplicate detection
"""

from simple_salesforce import Salesforce
import json
import csv
from datetime import datetime
import os
from dotenv import load_dotenv

# Load credentials from .env file
load_dotenv()

SF_USERNAME = os.getenv('SF_USERNAME')
SF_PASSWORD = os.getenv('SF_PASSWORD')
SF_SECURITY_TOKEN = os.getenv('SF_SECURITY_TOKEN')

def connect_to_salesforce():
    """Connect to Salesforce using username/password/token"""
    try:
        sf = Salesforce(
            username=SF_USERNAME,
            password=SF_PASSWORD,
            security_token=SF_SECURITY_TOKEN
        )
        print("✓ Connected to Salesforce successfully")
        return sf
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Get security token: Setup > My Personal Information > Reset My Security Token")
        print("2. Check if your IP needs to be whitelisted")
        print("3. For Connected App: See setup_connected_app.md")
        return None

def get_contacts(sf):
    """Pull all contacts with key fields for deduplication"""
    query = """
        SELECT Id, FirstName, LastName, Email, Phone, MobilePhone,
               MailingStreet, MailingCity, MailingState, MailingPostalCode,
               Title, AccountId, CreatedDate, LastModifiedDate
        FROM Contact
        ORDER BY LastName, FirstName
    """

    try:
        result = sf.query(query)
        contacts = result['records']
        print(f"✓ Retrieved {len(contacts)} contacts")
        return contacts
    except Exception as e:
        print(f"✗ Query failed: {e}")
        return []

def save_contacts(contacts, format='both'):
    """Save contacts to JSON and/or CSV"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if format in ['json', 'both']:
        json_file = f'contacts_{timestamp}.json'
        with open(json_file, 'w') as f:
            json.dump(contacts, f, indent=2, default=str)
        print(f"✓ Saved to {json_file}")

    if format in ['csv', 'both']:
        csv_file = f'contacts_{timestamp}.csv'
        if contacts:
            # Remove Salesforce metadata fields
            clean_contacts = []
            for c in contacts:
                clean = {k: v for k, v in c.items() if k != 'attributes'}
                clean_contacts.append(clean)

            keys = clean_contacts[0].keys()
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(clean_contacts)
            print(f"✓ Saved to {csv_file}")

def preview_contacts(contacts, limit=5):
    """Show a preview of the contacts"""
    print(f"\n--- Preview of {min(limit, len(contacts))} contacts ---")
    for i, contact in enumerate(contacts[:limit]):
        print(f"\n{i+1}. {contact.get('FirstName', '')} {contact.get('LastName', '')}")
        print(f"   Email: {contact.get('Email', 'N/A')}")
        print(f"   Phone: {contact.get('Phone', 'N/A')}")
        print(f"   ID: {contact.get('Id')}")

if __name__ == '__main__':
    print("=== Salesforce Contact Exporter ===\n")

    # Step 1: Connect
    sf = connect_to_salesforce()
    if not sf:
        exit(1)

    # Step 2: Get contacts
    contacts = get_contacts(sf)
    if not contacts:
        exit(1)

    # Step 3: Preview
    preview_contacts(contacts)

    # Step 4: Save
    save_contacts(contacts)

    print("\n✓ Done! Ready for duplicate detection.")
