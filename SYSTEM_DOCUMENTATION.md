# AI-Powered Contact Deduplication & Email Validation System

## Overview

This system uses Claude AI to identify duplicate contacts in Salesforce and validate email addresses, enabling data quality improvement at scale. The system is designed to build trust with stakeholders by flagging potential issues for human review rather than automatically deleting records.

## Business Objectives

1. **Email Hygiene**: Ensure 100% of contacts have valid, deliverable email addresses
2. **Duplicate Detection**: Identify and consolidate duplicate contact records
3. **Trust Building**: Provide transparent AI recommendations with human oversight
4. **Scalability**: Process millions of contacts efficiently through batch operations

---

## System Architecture

### Phase 1: Data Extraction
- Connects to Salesforce API (username/password/security token authentication)
- Extracts contacts with all relevant fields
- Pulls email activity data (Tasks, EmailMessages) for validation
- Groups contacts by Account for efficient duplicate detection

### Phase 2: Email Validation
- Analyzes email activity and bounce data
- Updates email status fields based on SFDC's native bounce tracking
- Marks contacts as Valid, Invalid, or Unknown

### Phase 3: Duplicate Detection (Claude AI)
- Compares contacts within each Account using Claude AI
- Detects name variations, typos, and email similarities
- Generates confidence scores and reasoning for each potential duplicate pair

### Phase 4: Duplicate Flagging & Review Preparation
- Marks both contacts in duplicate pairs for human review
- Generates narrative justifications explaining why records are duplicates
- Provides AI-suggested actions (Delete, Keep, or Merge)
- Sets review status to FALSE - awaiting human confirmation

### Phase 5: Human Review (SFDC Report)
- Account owners review duplicates in Salesforce report
- Grouped by `Duplicate_Group_Name__c` for side-by-side comparison
- Reviewers confirm or override AI suggestions
- Check `Duplicate_Reviewed__c` when complete

### Phase 6: Automated Cleanup (Future)
- Query contacts where `Duplicate_Reviewed__c = TRUE`
- Execute actions based on `Suggested_Action__c`
- Delete, merge, or keep records as confirmed by humans

---

## Custom Fields on Contact Object

### Email Validation Fields

#### `Email_Status__c` (Picklist)
**Values:** Valid | Invalid | Unknown | Duplicate

**Purpose:** Centralized email status tracking

**Usage:**
- **Valid**: Email confirmed deliverable (successful send in activity history, no bounce)
- **Invalid**: Email bounced or confirmed undeliverable
- **Unknown**: No activity data available to validate
- **Duplicate**: Contact flagged as potential duplicate (separate from email validity)

**Set by:** Phase 2 (email validation), Phase 4 (duplicate flagging)

---

#### `email_last_updated_date__c` (Date)
**Purpose:** Track when email status was last modified

**Usage:** Populated whenever email status changes; useful for reporting and tracking stale data

**Set by:** Phase 2, Phase 4

---

#### `Email_Verified_Date__c` (Date)
**Purpose:** Date when email was last successfully verified (sent without bounce)

**Usage:** Identifies when a contact's email was last confirmed working

**Set by:** Phase 2 (from successful email activity)

---

### Duplicate Detection Fields

#### `Duplicate_Group_Name__c` (Text, 100 chars)
**Purpose:** Groups duplicate contacts under a canonical name for reporting

**Usage:** All contacts in a duplicate set share the same group name (e.g., "Arthur Song")

**Logic:** System selects the most complete/formal name variant:
- Prefers longer names ("Benjamin" over "Ben")
- Prefers records with more complete data (phone, title)

**Set by:** Phase 4

**Report Usage:** Group by this field to see all duplicates side-by-side

---

#### `Duplicate_Justification__c` (Text Area, 255 chars)
**Purpose:** AI-generated narrative explaining why this contact is flagged

**Usage:** Provides context for reviewers about specific issues

**Examples:**
- "Likely typo/variant of 'Arthur Song'; missing phone and title"
- "Has phone and title; valid email"
- "Name capitalization differs from 'John Smith'; email bounced"

**Set by:** Phase 4 (AI-generated based on data comparison)

---

#### `Suggested_Action__c` (Picklist)
**Values:** Delete | Keep - Not a duplicate | Merge into other record

**Purpose:** AI recommendation for how to handle this contact

**Usage:**
- **Delete**: Contact is likely the incomplete/bad record
- **Keep - Not a duplicate**: Contact is likely the good record
- **Merge into other record**: Records are equal quality, should be merged

**Set by:** Phase 4 (AI determines based on scoring algorithm)

**Reviewer Action:** Can override this field if AI is wrong

---

#### `Duplicate_Reviewed__c` (Checkbox)
**Purpose:** Tracks whether a human has reviewed and confirmed the duplicate decision

**Default:** FALSE (unchecked)

**Usage:**
- Reviewer checks this box after confirming/modifying the suggested action
- Phase 6 automation only processes records where this is TRUE

**Set by:** Human reviewer in SFDC

---

## Native Salesforce Fields Used

### `EmailBouncedReason` (Text)
**Native SFDC Field**

**Purpose:** Automatically populated by Salesforce when an email bounces

**Usage:** PRIMARY field for detecting bounced emails. System checks this field to determine if email is Invalid.

**Example Values:**
- `550 5.4.1 Recipient address rejected: Access denied. For more information see https://aka.ms/EXOSmtpErrors [BN1PEPF0000467F.namprd03.prod.outlook.com 2025-10-05T18:50:13.740Z 08DE0366FCCF2B83]`
- `550 5.1.1 User unknown`
- `Mailbox full`

**Our Logic:** If this field has any value → mark `Email_Status__c = 'Invalid'`

---

### `EmailBouncedDate` (Date)
**Native SFDC Field**

**Purpose:** Automatically populated by Salesforce when an email bounces

**Usage:** Used by our system to track when the bounce occurred

**Our Logic:** Read this value to populate our custom `Email_Bounced_Date__c` for reporting consistency

---

### `IsEmailBounced` (Checkbox)
**Native SFDC Field**

**Purpose:** Boolean flag indicating if the email has bounced

**Usage:** Quick filter for bounced emails (TRUE = bounced, FALSE = not bounced)

**Our Logic:** Can use for quick filtering, but we primarily rely on `EmailBouncedReason` for validation logic

---

### Standard Contact Fields
- `FirstName`, `LastName` - Name comparison for duplicate detection
- `Email` - Primary deduplication key
- `Phone`, `MobilePhone` - Data completeness scoring
- `Title` - Data completeness scoring
- `AccountId`, `Account.Name` - Grouping for duplicate detection
- `LastModifiedDate` - Recency scoring

---

## Order of Operations

### 1. Data Extraction (Phase 1)
```
Input: Salesforce org with contacts
Output: JSON file with all contacts + activity data
```

**What it does:**
- Connects to SFDC API
- Queries all Contacts with custom and native fields
- Pulls email activity (Tasks, EmailMessages) from last 90 days
- Groups contacts by AccountId
- Saves checkpoint: `phase1_extraction.json`

---

### 2. Email Validation (Phase 2)
```
Input: phase1_extraction.json
Output: Updated SFDC contacts with email status
```

**Logic:**
1. Check native `EmailBouncedReason` field FIRST
   - If populated → `Email_Status__c = 'Invalid'`
   - Set `Email_Bounced_Date__c` from native `EmailBouncedDate`

2. If no bounce, check activity history
   - Successful email sends (Task Status = "Completed") → `Email_Status__c = 'Valid'`
   - Set `Email_Verified_Date__c` to send date

3. If no bounce and no activity → `Email_Status__c = 'Unknown'`

4. Update `email_last_updated_date__c = today`

**Saves:** `phase2_update_results.json`

---

### 3. Duplicate Detection (Phase 3)
```
Input: phase1_extraction.json
Output: JSON of duplicate pairs with AI reasoning
```

**Claude AI Prompt Logic:**
- Only flag duplicates if they're **the same person**
- DO NOT flag different people at same company
- DO flag:
  - Name variations: "Ben Fry" vs "Benjamin Fry"
  - Name typos: "Ben Fry" vs "Ben Frye"
  - Email variations: "ben.fry@gmail.com" vs "benjamin.fry@yahoo.com"
  - Same person with different contact info

**Output:**
- Confidence level (high/medium/low)
- Reasoning (why AI thinks they're duplicates)

**Saves:** `phase3_duplicates.json`, `phase3_slack_report.md`

---

### 4. Mark Duplicates for Review (Phase 4)
```
Input: phase3_duplicates.json, phase1_extraction.json
Output: Updated SFDC contacts with duplicate flags
```

**For each duplicate pair:**

1. **Determine Canonical Name**
   - Score based on length + data completeness
   - Prefer longer, more formal names
   - Both contacts get same `Duplicate_Group_Name__c`

2. **Score Contacts**
   - +1 for each: Phone, Mobile, Title
   - -2 for email bounce
   - +1 for longer name

3. **Assign Suggested Actions**
   - Lower score → `Suggested_Action__c = 'Delete'`
   - Higher score → `Suggested_Action__c = 'Keep - Not a duplicate'`
   - Equal scores → `Suggested_Action__c = 'Merge into other record'`

4. **Generate Justifications**
   - DELETE record: "Likely typo/variant of 'Other Name'; missing phone and title"
   - KEEP record: "Has phone and title; valid email"

5. **Update BOTH contacts:**
   - `Email_Status__c = 'Duplicate'`
   - `Duplicate_Group_Name__c = [canonical name]`
   - `Duplicate_Justification__c = [narrative]`
   - `Suggested_Action__c = [Delete/Keep/Merge]`
   - `Duplicate_Reviewed__c = FALSE`
   - `email_last_updated_date__c = today`

**Saves:** `phase4_duplicate_marking.json`

---

### 5. Human Review (Salesforce Report)

**Report Configuration:**
- **Filter:** `Email_Status__c = 'Duplicate'` AND `Duplicate_Reviewed__c = FALSE`
- **Group By:** `Duplicate_Group_Name__c`
- **Columns:**
  - Name
  - Email
  - Phone
  - Title
  - Last Activity Date
  - `EmailBouncedReason` (native field)
  - `Duplicate_Justification__c`
  - `Suggested_Action__c` (editable)
  - `Duplicate_Reviewed__c` (editable checkbox)

**Reviewer Workflow:**
1. Review both contacts in each group side-by-side
2. Read AI justification and suggested action
3. Confirm or override `Suggested_Action__c` dropdown
4. Check `Duplicate_Reviewed__c` box
5. Save

**Report can be:**
- Emailed/subscribed to account owners
- Slacked to teams for review
- Exported for bulk updates

---

### 6. Automated Cleanup (Future Phase)

**Query:**
```sql
SELECT Id, Suggested_Action__c, Duplicate_Group_Name__c
FROM Contact
WHERE Duplicate_Reviewed__c = TRUE
AND Email_Status__c = 'Duplicate'
```

**Actions:**
- **Delete**: Remove contact from SFDC
- **Keep - Not a duplicate**: Clear duplicate flags, restore to active
- **Merge into other record**: Use SFDC merge API to consolidate

---

## Future Enhancements

### Email Validation for Unknown Status
**Problem:** Contacts with no activity data (`Email_Status__c = 'Unknown'`)

**Solution:**
1. **API Validation (NeverBounce)**
   - Send unknown emails to NeverBounce API
   - Get validation result (valid/invalid/catch-all/unknown)
   - Update `Email_Status__c` accordingly

2. **Email Appending (Data Services)**
   - For contacts with invalid/missing emails
   - Purchase/append new email addresses from data providers
   - Re-validate using NeverBounce
   - Update contact with new email + mark as Valid

**Goal:** 100% of contacts have confirmed deliverable email addresses

---

## Scalability Considerations

### Current POC (20 contacts)
- Single batch processing
- Simple API calls

### Production Scale (Millions of contacts)

**Batch Processing:**
- Process 10,000 contacts per batch
- Can pause/resume without losing progress
- Avoid API rate limits

**Smart Pre-filtering:**
- Use SOQL queries to narrow duplicate candidates
  - Same last name
  - Same email domain
  - Same account
- Only send candidates to Claude AI (not all vs all comparison)

**Cost Optimization:**
- Use Claude Haiku for duplicate detection (cheaper, faster)
- Batch AI calls efficiently
- Cache results between phases

**Monitoring:**
- Log all AI decisions with confidence scores
- Track false positive/negative rates
- Adjust scoring algorithms based on feedback

---

## Key Design Decisions

### Why Flag Instead of Auto-Delete?
**Trust Building:** Stakeholders need to see the system works before giving delete permissions

### Why Group Contacts Instead of Picking Winner?
**Human Expertise:** Account owners know their data best and can override AI

### Why Both Custom and Native Fields?
**Flexibility:** Custom fields allow extended tracking beyond SFDC defaults
**Note:** May consolidate to native fields only in future

### Why Account-Based Grouping?
**Scalability:** Comparing contacts within accounts reduces comparisons from millions to hundreds
**Relevance:** Same person rarely appears across different accounts

---

## Error Handling

### Connection Failures
- Retry with exponential backoff
- Save progress checkpoints

### AI API Failures
- Skip account and log error
- Continue processing other accounts
- Re-run failed accounts separately

### SFDC Update Failures
- Log specific contact ID and error
- Save to error report for manual review
- Don't halt entire batch

---

## Reporting & Monitoring

### Key Metrics
- Total contacts processed
- Email validation results (Valid/Invalid/Unknown counts)
- Duplicate groups detected
- Duplicate review completion rate
- False positive rate (contacts marked "Keep - Not a duplicate")

### Reports for Stakeholders
1. **Email Health Dashboard**
   - % Valid emails
   - % Invalid/bounced
   - % Unknown (need external validation)

2. **Duplicate Detection Report**
   - Grouped by Account
   - Pending review vs. completed
   - AI confidence distribution

3. **Cleanup Progress**
   - Records deleted
   - Records merged
   - Records cleared (false positives)

---

## Best Practices

### For Developers
- Always save checkpoints between phases
- Test on small batches first (100 contacts)
- Monitor Claude API costs
- Use bulk API for SFDC updates

### For Reviewers
- Start with high-confidence duplicates
- Look for patterns in AI errors
- Provide feedback to improve scoring
- Don't trust AI blindly - verify data

### For Administrators
- Back up data before running Phase 6 (delete/merge)
- Set up sandbox testing first
- Monitor email deliverability after cleanup
- Track ROI (emails delivered vs. bounced)

---

## Contact for Questions
- **Technical Implementation:** See code in `/contacts` folder
- **Custom Field Details:** Check Salesforce Object Manager
- **AI Logic:** See `phase3_duplicate_detection.py` and `phase4_mark_duplicates.py`
