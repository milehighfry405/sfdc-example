# SFDC Deduplication Agent

AI-powered autonomous agent for Salesforce contact deduplication and email validation.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements_agent.txt
```

### 2. Configure Credentials

Make sure your `.env` file has:

```
# Salesforce
SF_USERNAME=your.email@example.com
SF_PASSWORD=yourpassword
SF_SECURITY_TOKEN=yourtoken

# Claude API
ANTHROPIC_API_KEY=sk-ant-xxxxx

# LangSmith (optional - for observability)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=lsv2_pt_xxxxx
LANGCHAIN_PROJECT=sfdc-dedup-agent
```

**Note:** See [LANGSMITH_SETUP.md](LANGSMITH_SETUP.md) for LangSmith integration details.

### 3. Run the Agent

**Full workflow (all 6 phases):**
```bash
python sfdc_agent.py
```

**Test with limited contacts:**
```bash
python sfdc_agent.py --batch-size 100
```

**Custom output directory:**
```bash
python sfdc_agent.py --output-dir my_reports
```

---

## What the Agent Does

The agent autonomously runs all 6 phases with human approval gates:

### Phase 1: Connect to Salesforce
- Authenticates using credentials from `.env`
- Validates connection

### Phase 2: Extract Contacts (Grouped by Account Owner)
- Pulls all contacts with custom fields
- Groups by Account Owner (for distributed review)
- Extracts email activity history

### Phase 3: Email Validation
- Checks SFDC native bounce fields (`EmailBouncedReason`, `EmailBouncedDate`)
- Analyzes email activity for successful sends
- Marks emails as Valid/Invalid/Unknown

### Phase 4: Duplicate Detection
- Uses Claude AI to detect duplicates within each Account Owner's contacts
- Only flags true duplicates (same person, not colleagues)
- Provides confidence scores (high/medium/low) and reasoning

### Phase 5: Mark Duplicates for Review
- **Human Approval Required**
- Shows preview of changes
- Marks BOTH contacts in duplicate pairs
- Sets review fields for human confirmation

### Phase 6: Update Salesforce
- **Human Approval Required**
- Batch updates contacts in SFDC
- Updates email status and duplicate flags

### Phase 7: Generate Reports
- Creates separate Markdown report per Account Owner
- Generates master summary JSON
- Saves cost report with LangSmith tracking
- Saves to `reports/` directory

---

## Observability & Cost Tracking

The agent integrates with **LangSmith** to track:
- Every Claude API call with costs
- Token usage (input/output)
- Performance metrics across all phases
- QA validation for duplicate detection

**View the dashboard:**
```bash
python view_dashboard.py
```

Then open `reports/dashboard.html` in your browser.

**Cost Summary Example:**
```
Cost Summary:
  - Total Cost: $0.0036
  - Total Tokens: 4,011
  - Runtime: 28s
  - Cost/Minute: $0.0078

Cost by Phase:
  - duplicate_detection: 6 calls, $0.0036, 4011 tokens
```

**See [LANGSMITH_SETUP.md](LANGSMITH_SETUP.md) for complete setup instructions.**

---

## Human Approval Checkpoints

The agent pauses at two critical points:

### Checkpoint 1: Before Marking Duplicates
```
=== HUMAN APPROVAL REQUIRED ===

Ready to mark 30 contacts as duplicates.
This will update the following fields in Salesforce:
  - Email_Status__c = 'Duplicate'
  - Duplicate_Group_Name__c
  - Duplicate_Justification__c
  - Suggested_Action__c
  - Duplicate_Reviewed__c = FALSE

Sample duplicate group:
[Shows preview of one duplicate pair]

Proceed with marking duplicates in Salesforce? (yes/no):
```

Type `yes` to proceed or `no` to cancel.

### Checkpoint 2: Before Updating Salesforce
```
=== FINAL APPROVAL REQUIRED ===

Ready to update 50 contacts in Salesforce.

Proceed with Salesforce update? (yes/no):
```

Type `yes` to proceed or `no` to cancel.

---

## Output Files

All reports are saved to `reports/` directory:

### Per-Account Owner Reports
```
reports/
  ├── John_Smith_duplicates.md       # Report for John Smith
  ├── Jane_Doe_duplicates.md         # Report for Jane Doe
  ├── Bob_Johnson_duplicates.md      # Report for Bob Johnson
  └── master_summary.json            # Aggregate statistics
```

### Account Owner Report Format

Each Markdown report shows:
- Duplicate pairs grouped by Account
- Side-by-side comparison table
- AI confidence and reasoning
- Justifications for each contact
- Suggested actions (Delete/Keep/Merge)
- Next steps for review

**Example:**

```markdown
# Duplicate Contacts Report - John Smith

Generated: 2025-10-05 14:30:00

**Total Duplicate Pairs: 3**

---

## Duplicate Pair #1 - HIGH Confidence

**Account:** United Oil & Gas Corp.
**Group Name:** Arthur Song
**AI Reasoning:** Nearly identical names with slight variation...

| Field | Contact A | Contact B |
|-------|-----------|-----------|
| **Name** | Arthur Song | Arther Soong |
| **Email** | asong@uog.com | a.song@uog.com |
| **Phone** | (212) 842-5500 | N/A |
| **Title** | CEO | N/A |
| **Justification** | Has phone and title; valid email | Likely typo/variant of 'Arthur Song'; missing phone and title |
| **Suggested Action** | Keep - Not a duplicate | Delete |
| **SFDC ID** | `003xxx1` | `003xxx2` |

**Next Steps:**
1. Review both contacts in Salesforce
2. Verify the suggested action is correct
3. Update `Suggested_Action__c` field if needed
4. Check `Duplicate_Reviewed__c` checkbox to mark as reviewed
```

---

## Account Owner Review Workflow

After the agent runs, distribute reports to Account Owners:

1. **Email/Slack the Markdown report** to each owner
   - `John_Smith_duplicates.md` → Email to John Smith
   - `Jane_Doe_duplicates.md` → Email to Jane Doe

2. **Owner reviews in Salesforce:**
   - Go to Contacts
   - Filter: `Email_Status__c = 'Duplicate'` AND `Duplicate_Reviewed__c = FALSE`
   - Group by: `Duplicate_Group_Name__c`

3. **Owner confirms or overrides:**
   - Review each duplicate group
   - Change `Suggested_Action__c` if AI is wrong
   - Check `Duplicate_Reviewed__c` box when done

4. **Future automation (Phase 6):**
   - Query for `Duplicate_Reviewed__c = TRUE`
   - Execute the confirmed action (Delete/Merge/Keep)

---

## Scalability for 2M Records

The agent is designed to handle millions of contacts:

### Batching Strategy
- Process contacts in configurable batches (default: all at once)
- Use `--batch-size` flag to limit for testing
- For production: Run multiple times with owner filters

### Account Owner Grouping
- Contacts are grouped by Account Owner FIRST
- Each owner's contacts are analyzed together
- Reports are separated by owner
- Owners can review their contacts independently

### Parallel Processing (Future Enhancement)
Current version processes sequentially. For 2M records, you can:

**Option 1: Run by owner segment**
```bash
# Day 1: Process owners A-E
python sfdc_agent.py --owner-filter "A-E"

# Day 2: Process owners F-J
python sfdc_agent.py --owner-filter "F-J"
```

**Option 2: Run in batches**
```bash
# Batch 1: First 100K contacts
python sfdc_agent.py --batch-size 100000

# Batch 2: Next 100K contacts
python sfdc_agent.py --batch-size 100000 --offset 100000
```

### Checkpointing
- Agent saves progress after each phase
- Can resume from `reports/agent_checkpoint.json` if interrupted
- Safe to stop and restart

---

## Monitoring Progress

The agent prints detailed progress:

```
======================================================================
SFDC CONTACT DEDUPLICATION & EMAIL VALIDATION AGENT
======================================================================

[PHASE 1] Connecting to Salesforce...
[OK] Connected to Salesforce successfully

[PHASE 2] Extracting contacts grouped by Account Owner...
[OK] Retrieved 21 contacts
[OK] Grouped into 5 Account Owners:
     - John Smith: 8 contacts
     - Jane Doe: 6 contacts
     - Bob Johnson: 4 contacts
     - Alice Brown: 2 contacts
     - Charlie Davis: 1 contacts

[PHASE 3] Validating email addresses...
[OK] Found 1 email Task records
[OK] Email validation complete:
     - Valid: 1
     - Invalid: 0
     - Unknown: 20
     - Updates needed: 1

[PHASE 4] Detecting duplicates per Account Owner...
  Analyzing John Smith (8 contacts)...
    -> Found 2 duplicate pair(s)
  Analyzing Jane Doe (6 contacts)...
    -> No duplicates found
  ...

[OK] Total duplicate pairs found: 3

[PHASE 5] Preparing duplicate marking...
[OK] Prepared 6 contact updates
[OK] Created 3 duplicate groups

[HUMAN APPROVAL CHECKPOINT]
...

[PHASE 6] Updating Salesforce...
[OK] Salesforce update complete:
     - Success: 6
     - Errors: 0

[PHASE 7] Generating reports per Account Owner...
  [OK] Generated report for John Smith: reports/John_Smith_duplicates.md
  [OK] Generated report for Jane Doe: reports/Jane_Doe_duplicates.md
  [OK] Generated master summary: reports/master_summary.json

======================================================================
AGENT WORKFLOW COMPLETE
======================================================================

Summary:
  - Contacts processed: 21
  - Account Owners: 5
  - Emails validated: 21
  - Duplicates found: 3
  - Salesforce updates: 6

Reports saved to: reports/
```

---

## Troubleshooting

### "Connection failed: INVALID_LOGIN"
- Check credentials in `.env` file
- Verify security token is current
- Try resetting security token in SFDC

### "Claude API failed: invalid x-api-key"
- Check `ANTHROPIC_API_KEY` in `.env`
- Verify API key is valid at https://console.anthropic.com/

### Agent finds no duplicates in test data
- Sample data may not have real duplicates
- Try creating test duplicates:
  - Same person, different emails
  - Name typos (Ben Fry vs Ben Frye)

### Memory issues with large batches
- Use `--batch-size 10000` to limit contacts
- Process in smaller chunks
- Run overnight for millions of records

---

## Next Steps After POC

### 1. Validate Results
- Review the generated reports
- Check accuracy of duplicate detection
- Verify email validation logic

### 2. Distribute to Account Owners
- Email Markdown reports to owners
- Train owners on SFDC review workflow
- Collect feedback on AI accuracy

### 3. Production Deployment
- Schedule as nightly job (cron/Airflow)
- Add Slack notifications
- Implement Phase 6 (automated cleanup based on reviews)

### 4. Scale to 2M Records
- Add owner filtering
- Implement parallel processing
- Optimize batch sizes

---

## Files in This Project

```
contacts/
├── agent_tools.py              # Refactored tools from phase scripts
├── sfdc_agent.py               # Main agent orchestrator
├── requirements_agent.txt      # Python dependencies
├── .env                        # Credentials (not in git)
├── README_AGENT.md            # This file
├── SYSTEM_DOCUMENTATION.md     # Field definitions and workflow
├── AGENT_DESIGN.md            # Architecture design doc
└── reports/                    # Generated reports (created at runtime)
    ├── John_Smith_duplicates.md
    ├── Jane_Doe_duplicates.md
    ├── master_summary.json
    └── agent_checkpoint.json
```

---

## Questions?

See `SYSTEM_DOCUMENTATION.md` for detailed field definitions and workflow explanation.
See `AGENT_DESIGN.md` for architecture and SDK implementation details.
