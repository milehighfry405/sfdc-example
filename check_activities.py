"""
Quick script to check what email activity data exists in SFDC
"""

from simple_salesforce import Salesforce
import os
from dotenv import load_dotenv

load_dotenv()

sf = Salesforce(
    username=os.getenv('SF_USERNAME'),
    password=os.getenv('SF_PASSWORD'),
    security_token=os.getenv('SF_SECURITY_TOKEN')
)

print("=== Checking for Email Activities ===\n")

# Try to query EmailMessage
print("1. Checking EmailMessage object...")
try:
    result = sf.query("SELECT Id, Subject, Status, CreatedDate FROM EmailMessage LIMIT 5")
    print(f"   Found {result['totalSize']} EmailMessage records")
    if result['records']:
        for record in result['records'][:3]:
            print(f"   - {record['Subject']}: {record['Status']}")
except Exception as e:
    print(f"   Error: {e}")

print("\n2. Checking Task object (email tasks)...")
try:
    result = sf.query("SELECT Id, Subject, Status, CreatedDate FROM Task WHERE TaskSubtype = 'Email' LIMIT 5")
    print(f"   Found {result['totalSize']} email Task records")
    if result['records']:
        for record in result['records'][:3]:
            print(f"   - {record['Subject']}: {record['Status']}")
except Exception as e:
    print(f"   Error: {e}")

print("\n3. Checking all Tasks...")
try:
    result = sf.query("SELECT Id, Subject, Type, CreatedDate FROM Task LIMIT 10")
    print(f"   Found {result['totalSize']} total Task records")
    if result['records']:
        for record in result['records'][:5]:
            print(f"   - {record.get('Subject', 'No subject')}: Type={record.get('Type', 'N/A')}")
except Exception as e:
    print(f"   Error: {e}")

print("\n4. Checking ActivityHistory...")
try:
    # Get a contact ID first
    contact = sf.query("SELECT Id FROM Contact LIMIT 1")['records'][0]
    contact_id = contact['Id']

    result = sf.query(f"SELECT Id, Subject, ActivityType FROM ActivityHistory WHERE WhoId = '{contact_id}' LIMIT 5")
    print(f"   Found {result['totalSize']} ActivityHistory records for sample contact")
    if result['records']:
        for record in result['records'][:3]:
            print(f"   - {record.get('Subject', 'No subject')}: {record.get('ActivityType', 'N/A')}")
except Exception as e:
    print(f"   Error: {e}")
