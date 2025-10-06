# LangSmith Integration Guide

This guide explains how the SFDC Deduplication Agent integrates with LangSmith for observability, cost tracking, and QA validation.

---

## What is LangSmith?

LangSmith is an observability platform for LLM applications. It provides:
- **Tracing**: Track every Claude API call with inputs, outputs, and metadata
- **Cost Tracking**: Monitor token usage and costs across all operations
- **Performance Monitoring**: Measure latency, success rates, and errors
- **QA Validation**: Automatically detect issues in AI outputs

---

## Setup Instructions

### 1. Get Your LangSmith API Key

1. Go to [https://smith.langchain.com/](https://smith.langchain.com/)
2. Sign up for a free account
3. Navigate to **Settings** → **API Keys**
4. Create a new API key
5. Copy the key (starts with `lsv2_pt_...`)

### 2. Configure Environment Variables

Add your LangSmith credentials to `.env`:

```bash
# LangSmith (observability & monitoring)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=lsv2_pt_your_actual_key_here
LANGCHAIN_PROJECT=sfdc-dedup-agent
```

**Important:** Replace `lsv2_pt_your_actual_key_here` with your actual API key from Step 1.

### 3. Verify Integration

Run the agent to test:

```bash
python sfdc_agent.py --auto-approve
```

If LangSmith is configured correctly, you'll see:
- Cost tracking output at the end
- A `cost_report.json` file in the `reports/` directory
- Traces appearing in your LangSmith dashboard at [https://smith.langchain.com/](https://smith.langchain.com/)

---

## What Gets Tracked?

### 1. **Duplicate Detection (Claude API Calls)**
Every call to Claude for duplicate detection is traced with:
- **Inputs**: Contact data formatted for analysis
- **Outputs**: Duplicate pairs detected
- **Metadata**:
  - Account Owner name and ID
  - Account name being analyzed
  - Number of contacts processed
  - Model used (`claude-3-5-haiku-20241022`)
- **Costs**: Token usage (input/output) and dollar cost

### 2. **Email Validation**
- **Logic traced**: Bounce detection and activity analysis
- **Outputs**: Validation stats (Valid/Invalid/Unknown counts)
- **Metadata**: Number of contacts processed

### 3. **Duplicate Marking**
- **Logic traced**: Scoring and justification generation
- **Outputs**: Update payloads and decisions
- **QA Validation**: Flags potential issues like:
  - Both contacts marked for deletion (shouldn't happen)
  - Inconsistent account names

### 4. **Salesforce Updates**
- **Logic traced**: Batch update operations
- **Outputs**: Success/error counts
- **Metadata**: Batch size, sample errors

---

## Cost Tracking

The agent tracks costs at multiple levels:

### Global Cost Tracker
Accumulates costs across all phases:
```python
{
  "total_cost": 0.0036,              # Total USD
  "total_tokens": 4011,              # Input + output tokens
  "runtime_seconds": 28.0,
  "cost_per_minute": 0.0078,         # Projected cost per minute
  "calls_by_phase": {
    "duplicate_detection": {
      "count": 6,                     # Number of API calls
      "cost": 0.0036,                 # USD
      "tokens": 4011
    },
    "email_validation": { ... },
    "other": { ... }
  }
}
```

### Pricing (as of 2025)
- **Claude 3.5 Haiku**: $0.80 per 1M input tokens, $4.00 per 1M output tokens
- **Claude Sonnet 4.5**: $3.00 per 1M input tokens, $15.00 per 1M output tokens

---

## Viewing Results

### Option 1: Cost Report JSON
After each run, check:
```bash
cat reports/cost_report.json
```

### Option 2: Interactive Dashboard
Generate and view an HTML dashboard:
```bash
python view_dashboard.py
```

Then open `reports/dashboard.html` in your browser.

The dashboard shows:
- Total cost and token usage
- Cost breakdown by phase
- Workflow metrics (contacts processed, duplicates found, etc.)
- Email validation stats
- Duplicate detection confidence levels

### Option 3: LangSmith Web UI
1. Go to [https://smith.langchain.com/](https://smith.langchain.com/)
2. Select your project: `sfdc-dedup-agent`
3. View all traces, filter by tags, search by metadata
4. Drill down into individual Claude API calls

---

## QA Validation Features

The LangSmith integration includes automatic quality checks:

### 1. **Duplicate Marking Validation**
Detects potential issues in duplicate detection:
- **Both marked for deletion**: If both contacts in a pair are suggested for deletion, this is logged as a QA issue
- **Different account names**: If duplicates are detected across different accounts (shouldn't happen)

Example QA issue logged to LangSmith:
```json
{
  "qa_issues": [
    {
      "type": "both_marked_delete",
      "group": "Arthur Song"
    }
  ]
}
```

### 2. **Parse Error Tracking**
If Claude's JSON response can't be parsed:
- Raw response is logged (first 500 chars)
- Parse error message is captured
- Allows you to diagnose prompt issues

---

## Architecture Overview

```
┌─────────────────┐
│  sfdc_agent.py  │  Main orchestrator
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ agent_tools.py  │  Tool functions (delegates to traced wrappers)
└────────┬────────┘
         │
         ↓
┌──────────────────────┐
│ langsmith_wrapper.py │  LangSmith @traceable decorators
└──────────┬───────────┘
           │
           ↓
┌──────────────────────┐
│    LangSmith API     │  Sends traces to cloud
└──────────────────────┘
```

### Key Files

1. **`langsmith_wrapper.py`**: Contains all traced functions with `@traceable` decorators
2. **`agent_tools.py`**: Imports traced functions and delegates to them
3. **`sfdc_agent.py`**: Calls agent_tools and saves cost report at end
4. **`view_dashboard.py`**: Generates HTML dashboard from reports

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'langsmith'"
Install dependencies:
```bash
pip install -r requirements_agent.txt
```

### Traces Not Appearing in LangSmith
1. Verify your API key is correct in `.env`
2. Check that `LANGCHAIN_TRACING_V2=true` is set
3. Ensure you're logged into the correct LangSmith account
4. Check your project name matches: `LANGCHAIN_PROJECT=sfdc-dedup-agent`

### Cost Report Shows $0.00
- Email validation and duplicate marking don't call Claude API (no cost)
- Only duplicate detection uses Claude
- If no duplicates are found, no API calls are made

---

## Scaling Considerations

For production use with millions of contacts:

### Cost Projections
Based on test run (21 contacts, $0.0036):
- **Cost per contact**: ~$0.00017
- **1,000 contacts**: ~$0.17
- **10,000 contacts**: ~$1.70
- **100,000 contacts**: ~$17.00
- **1,000,000 contacts**: ~$170.00

**Note**: Actual costs will vary based on:
- Number of contacts per account (affects prompt size)
- Duplicate density (more duplicates = more API calls)
- Model choice (Haiku vs Sonnet)

### Optimization Tips
1. **Use batching**: Process contacts in smaller groups by Account Owner
2. **Filter contacts**: Only analyze accounts with 2+ contacts
3. **Use Haiku model**: 3-4x cheaper than Sonnet for this use case
4. **Cache results**: Store duplicate detection results to avoid re-analysis

---

## Next Steps

Once LangSmith is integrated, you can:

1. **Track accuracy over time**: Compare AI suggestions vs. human decisions
2. **A/B test prompts**: Try different duplicate detection prompts and measure results
3. **Monitor production**: Set up alerts for high costs or error rates
4. **Build feedback loops**: Use human feedback to improve duplicate detection

---

## Support

- LangSmith Docs: [https://docs.smith.langchain.com/](https://docs.smith.langchain.com/)
- LangSmith Community: [https://github.com/langchain-ai/langsmith-sdk](https://github.com/langchain-ai/langsmith-sdk)
