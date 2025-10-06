# SFDC Deduplication Agent - Architecture Design

## Overview

Transform the current Python scripts into a **Claude Agent** that can autonomously run the entire contact deduplication and email validation workflow with human oversight.

---

## Agent Architecture (Claude Agent SDK)

### Core Agent Loop

```
┌─────────────────────────────────────────┐
│  1. GATHER CONTEXT                      │
│  - Connect to Salesforce                │
│  - Pull contact data                    │
│  - Read activity history                │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  2. TAKE ACTION                         │
│  - Validate emails                      │
│  - Detect duplicates                    │
│  - Mark records for review              │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  3. VERIFY WORK                         │
│  - Check update success                 │
│  - Generate reports                     │
│  - Log decisions                        │
└─────────────────────────────────────────┘
```

---

## Tool Definitions (Python with @beta_tool)

### 1. Salesforce Connection Tool

```python
from anthropic import beta_tool
from simple_salesforce import Salesforce
import os

@beta_tool
def connect_to_salesforce() -> str:
    """
    Connect to Salesforce using credentials from environment variables.
    Returns connection status and org information.
    """
    try:
        sf = Salesforce(
            username=os.getenv('SF_USERNAME'),
            password=os.getenv('SF_PASSWORD'),
            security_token=os.getenv('SF_SECURITY_TOKEN')
        )
        return json.dumps({
            "status": "success",
            "message": "Connected to Salesforce",
            "connection": sf
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Connection failed: {str(e)}"
        })
```

---

### 2. Extract Contacts Tool

```python
@beta_tool
def extract_contacts(
    sf_connection: object,
    include_activities: bool = True,
    batch_size: int = 10000
) -> str:
    """
    Extract contacts from Salesforce with custom fields and activity data.

    Args:
        sf_connection: Active Salesforce connection
        include_activities: Whether to pull email activity history
        batch_size: Number of contacts to process (for batching)

    Returns:
        JSON with contact data and metadata
    """
    # Implementation from phase1_extraction.py
    contacts = extract_contacts_impl(sf_connection)

    if include_activities:
        activities = extract_email_activities(sf_connection, contacts)

    return json.dumps({
        "total_contacts": len(contacts),
        "contacts": contacts,
        "activities": activities,
        "grouped_by_account": group_contacts_by_account(contacts)
    })
```

---

### 3. Validate Emails Tool

```python
@beta_tool
def validate_emails(contacts: list, activities: dict) -> str:
    """
    Validate email addresses based on SFDC bounce data and activity history.

    Args:
        contacts: List of contact records
        activities: Email activity data by contact ID

    Returns:
        JSON with validation results and update payloads
    """
    # Implementation from phase2_email_validation.py
    updates = []

    for contact in contacts:
        validation_result = validate_email_from_activities(contact, activities)
        updates.append({
            'Id': contact['Id'],
            **validation_result
        })

    return json.dumps({
        "total_updates": len(updates),
        "valid_count": sum(1 for u in updates if u['Email_Status__c'] == 'Valid'),
        "invalid_count": sum(1 for u in updates if u['Email_Status__c'] == 'Invalid'),
        "unknown_count": sum(1 for u in updates if u['Email_Status__c'] == 'Unknown'),
        "updates": updates
    })
```

---

### 4. Detect Duplicates Tool

```python
@beta_tool
def detect_duplicates(
    grouped_contacts: dict,
    confidence_threshold: str = "medium"
) -> str:
    """
    Use Claude AI to detect duplicate contacts within each account.

    Args:
        grouped_contacts: Contacts grouped by AccountId
        confidence_threshold: Minimum confidence level (low/medium/high)

    Returns:
        JSON with duplicate pairs and AI reasoning
    """
    # Implementation from phase3_duplicate_detection.py
    # Uses nested Claude API call for duplicate analysis

    duplicates = analyze_all_accounts(grouped_contacts, claude_client)

    return json.dumps({
        "total_duplicate_pairs": len(duplicates),
        "duplicates_by_account": duplicates,
        "high_confidence_count": count_by_confidence(duplicates, "high"),
        "medium_confidence_count": count_by_confidence(duplicates, "medium"),
        "low_confidence_count": count_by_confidence(duplicates, "low")
    })
```

---

### 5. Mark Duplicates for Review Tool

```python
@beta_tool
def mark_duplicates_for_review(
    duplicates_data: dict,
    contacts_dict: dict
) -> str:
    """
    Mark both contacts in duplicate pairs with review fields.

    Args:
        duplicates_data: Detected duplicate pairs with reasoning
        contacts_dict: Contact lookup by ID

    Returns:
        JSON with update payloads and decisions
    """
    # Implementation from phase4_mark_duplicates.py

    updates = []
    decisions = []

    for account_id, data in duplicates_data['duplicates_by_account'].items():
        for pair in data['duplicates']:
            # Generate canonical name, justifications, suggested actions
            canonical_name = determine_canonical_name(contact1, contact2)

            # Create updates for BOTH contacts
            updates.extend([
                {
                    'Id': contact_id_1,
                    'Email_Status__c': 'Duplicate',
                    'Duplicate_Group_Name__c': canonical_name,
                    'Duplicate_Justification__c': justification_1,
                    'Suggested_Action__c': suggested_action_1,
                    'Duplicate_Reviewed__c': False
                },
                # ... contact 2 update
            ])

    return json.dumps({
        "total_updates": len(updates),
        "duplicate_groups": len(decisions),
        "updates": updates,
        "decisions": decisions
    })
```

---

### 6. Update Salesforce Tool

```python
@beta_tool
def update_salesforce_contacts(
    sf_connection: object,
    updates: list,
    batch_size: int = 200
) -> str:
    """
    Batch update contacts in Salesforce.

    Args:
        sf_connection: Active Salesforce connection
        updates: List of contact update payloads
        batch_size: Records per batch

    Returns:
        JSON with success/error counts
    """
    success_count = 0
    errors = []

    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        results = sf_connection.bulk.Contact.update(batch)

        for idx, result in enumerate(results):
            if result['success']:
                success_count += 1
            else:
                errors.append({
                    'contact_id': batch[idx]['Id'],
                    'error': result.get('errors')
                })

    return json.dumps({
        "success_count": success_count,
        "error_count": len(errors),
        "errors": errors[:10]  # Limit error details
    })
```

---

### 7. Generate Report Tool

```python
@beta_tool
def generate_duplicate_report(
    decisions: list,
    contacts_dict: dict,
    format: str = "markdown"
) -> str:
    """
    Generate human-readable duplicate detection report.

    Args:
        decisions: Duplicate marking decisions
        contacts_dict: Contact lookup by ID
        format: Output format (markdown/json/csv)

    Returns:
        Formatted report as string
    """
    # Implementation from phase3_duplicate_detection.py

    if format == "markdown":
        return generate_slack_report(decisions, contacts_dict)
    elif format == "json":
        return json.dumps(decisions, indent=2)
    # ... other formats
```

---

## Agent Workflow Definition

### Main Agent Runner

```python
from anthropic import Anthropic, beta_tool
import json
import os

class SFDCDeduplicationAgent:
    def __init__(self):
        self.client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        self.sf_connection = None
        self.tools = [
            connect_to_salesforce,
            extract_contacts,
            validate_emails,
            detect_duplicates,
            mark_duplicates_for_review,
            update_salesforce_contacts,
            generate_duplicate_report
        ]

    def run(self, task: str):
        """
        Run the agent with a specific task instruction.

        Args:
            task: Natural language instruction for the agent

        Example tasks:
        - "Process all contacts for duplicates and email validation"
        - "Run email validation only on contacts with Unknown status"
        - "Detect duplicates for United Oil & Gas Corp account only"
        """

        runner = self.client.beta.messages.tool_runner(
            max_tokens=4096,
            model="claude-sonnet-4-5-20250929",
            tools=self.tools,
            messages=[
                {
                    "role": "user",
                    "content": f"""You are a Salesforce contact deduplication and email validation agent.

Your task: {task}

Follow these steps:
1. Connect to Salesforce using connect_to_salesforce()
2. Extract contacts with extract_contacts()
3. Validate emails using validate_emails()
4. Detect duplicates using detect_duplicates()
5. Mark duplicates for review using mark_duplicates_for_review()
6. Update Salesforce using update_salesforce_contacts()
7. Generate a report using generate_duplicate_report()

After each step, verify success before proceeding.
Provide progress updates and handle errors gracefully.
"""
                }
            ]
        )

        # Process agent loop
        for message in runner:
            print(f"Agent: {message}")

            # Optional: Add human-in-the-loop checkpoints
            if self._requires_approval(message):
                if not self._get_human_approval(message):
                    break

        return runner.final_result

    def _requires_approval(self, message):
        """Check if message requires human approval"""
        # Define checkpoints: before updating SFDC, before marking duplicates, etc.
        return any(keyword in str(message) for keyword in [
            "update_salesforce_contacts",
            "mark_duplicates_for_review"
        ])

    def _get_human_approval(self, message):
        """Get human approval for action"""
        print(f"\nAction requires approval: {message}")
        response = input("Approve? (yes/no): ")
        return response.lower() == 'yes'


# Usage
if __name__ == '__main__':
    agent = SFDCDeduplicationAgent()

    # Run full workflow
    result = agent.run("Process all contacts for duplicates and email validation")

    print(f"Final result: {result}")
```

---

## Subagent Pattern (Parallel Processing)

For large-scale operations, use subagents to process accounts in parallel:

```python
class AccountDeduplicationSubagent:
    """Subagent that processes a single account"""

    def __init__(self, account_id: str, contacts: list):
        self.account_id = account_id
        self.contacts = contacts
        self.client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    def run(self):
        """Run duplicate detection for this account only"""
        runner = self.client.beta.messages.tool_runner(
            max_tokens=2048,
            model="claude-3-5-haiku-20241022",  # Cheaper model for subagents
            tools=[detect_duplicates_single_account],
            messages=[{
                "role": "user",
                "content": f"Detect duplicates for account {self.account_id}"
            }]
        )

        return runner.final_result


# Main agent spawns subagents
def process_accounts_parallel(grouped_contacts):
    """Process each account with a separate subagent"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []

        for account_id, contacts in grouped_contacts.items():
            subagent = AccountDeduplicationSubagent(account_id, contacts)
            futures.append(executor.submit(subagent.run))

        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    return results
```

---

## Deployment Options

### 1. CLI Tool (Local)
```bash
python sfdc_agent.py --task "full_workflow" --batch-size 10000
```

### 2. Web API (FastAPI)
```python
from fastapi import FastAPI
app = FastAPI()

@app.post("/run-dedup")
async def run_deduplication(task: str):
    agent = SFDCDeduplicationAgent()
    result = agent.run(task)
    return {"result": result}
```

### 3. Scheduled Job (Airflow/Cron)
```python
# Run nightly at 2am
@schedule.every().day.at("02:00")
def nightly_dedup_job():
    agent = SFDCDeduplicationAgent()
    agent.run("Process all contacts updated in last 24 hours")
```

### 4. Slack Bot Integration
```python
@slack_app.command("/find-duplicates")
def handle_slack_command(ack, command):
    ack()
    account_name = command['text']

    agent = SFDCDeduplicationAgent()
    result = agent.run(f"Detect duplicates for account: {account_name}")

    # Post result to Slack channel
    slack_client.chat_postMessage(
        channel=command['channel_id'],
        text=result
    )
```

---

## Human-in-the-Loop Checkpoints

### Approval Gates

```python
class HumanApprovalAgent(SFDCDeduplicationAgent):
    """Agent with mandatory approval checkpoints"""

    CHECKPOINT_PHASES = [
        "before_email_validation",
        "before_duplicate_detection",
        "before_marking_duplicates",
        "before_updating_salesforce"
    ]

    def run_with_approvals(self, task: str):
        """Run workflow with human approval at each checkpoint"""

        for phase in self.CHECKPOINT_PHASES:
            print(f"\n=== CHECKPOINT: {phase} ===")

            # Show preview of what will happen
            preview = self._get_phase_preview(phase)
            print(preview)

            # Get approval
            if not self._get_human_approval(f"Proceed with {phase}?"):
                print(f"Workflow stopped at {phase}")
                return

            # Execute phase
            self._execute_phase(phase)

        print("\n=== Workflow Complete ===")
```

---

## Error Handling & Retry Logic

```python
@beta_tool
def safe_update_salesforce(updates: list, max_retries: int = 3) -> str:
    """
    Update Salesforce with automatic retry on transient failures.
    """
    for attempt in range(max_retries):
        try:
            result = update_salesforce_contacts(sf, updates)
            return result
        except TransientError as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            else:
                return json.dumps({
                    "status": "error",
                    "message": f"Failed after {max_retries} attempts",
                    "error": str(e)
                })
```

---

## Monitoring & Logging

```python
class MonitoredAgent(SFDCDeduplicationAgent):
    """Agent with comprehensive logging and metrics"""

    def __init__(self):
        super().__init__()
        self.metrics = {
            "contacts_processed": 0,
            "emails_validated": 0,
            "duplicates_found": 0,
            "sfdc_updates": 0,
            "errors": []
        }

    def run(self, task: str):
        start_time = datetime.now()

        try:
            result = super().run(task)

            # Log success metrics
            self._log_metrics(success=True, duration=datetime.now() - start_time)

            return result

        except Exception as e:
            # Log failure
            self._log_metrics(success=False, error=str(e))
            raise

    def _log_metrics(self, success: bool, **kwargs):
        """Send metrics to monitoring system"""
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "metrics": self.metrics,
            **kwargs
        }

        # Send to CloudWatch, Datadog, etc.
        print(json.dumps(log_data))
```

---

## Configuration Management

```python
# agent_config.yaml
agent:
  model: "claude-sonnet-4-5-20250929"
  max_tokens: 4096
  temperature: 0.0  # Deterministic for production

tools:
  detect_duplicates:
    confidence_threshold: "medium"
    model: "claude-3-5-haiku-20241022"  # Cheaper model for subprocesses

  update_salesforce:
    batch_size: 200
    max_retries: 3

checkpoints:
  require_approval:
    - before_marking_duplicates
    - before_updating_salesforce

monitoring:
  log_level: "INFO"
  metrics_endpoint: "https://metrics.company.com/api/v1"
```

---

## Security Considerations

### Credential Management
```python
# Use environment variables or secret management
from azure.keyvault.secrets import SecretClient

def get_sfdc_credentials():
    """Fetch credentials from Azure Key Vault"""
    client = SecretClient(vault_url=VAULT_URL, credential=credential)

    return {
        'username': client.get_secret('sfdc-username').value,
        'password': client.get_secret('sfdc-password').value,
        'token': client.get_secret('sfdc-security-token').value
    }
```

### Audit Trail
```python
@beta_tool
def audit_log(action: str, contact_ids: list, result: str):
    """Log all agent actions for compliance"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "contact_ids": contact_ids,
        "result": result,
        "agent_version": "1.0.0"
    }

    # Write to audit database
    audit_db.insert(log_entry)
```

---

## Testing Strategy

### Unit Tests for Tools
```python
def test_validate_emails_tool():
    """Test email validation logic"""
    contact = {
        'Id': '003xxx',
        'EmailBouncedReason': '550 User unknown'
    }

    result = validate_emails([contact], {})
    assert result['Email_Status__c'] == 'Invalid'
```

### Integration Tests
```python
def test_full_agent_workflow():
    """Test entire agent workflow end-to-end"""
    agent = SFDCDeduplicationAgent()

    # Mock SFDC connection
    with patch('simple_salesforce.Salesforce'):
        result = agent.run("Process test account")

        assert result['success'] == True
        assert 'duplicate_pairs' in result
```

---

## Next Steps to Ship

1. **Refactor existing scripts into @beta_tool functions**
2. **Create main agent runner with tool_runner()**
3. **Add human approval checkpoints**
4. **Implement error handling and retries**
5. **Set up monitoring and logging**
6. **Deploy as API or CLI tool**
7. **Create user documentation and runbook**

---

## Resources

- [Claude Agent SDK Docs](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
- [Agent Quickstarts](https://github.com/anthropics/anthropic-quickstarts)
