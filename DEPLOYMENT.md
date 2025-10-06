# SFDC Deduplication Agent - Railway Deployment Guide

Complete guide for deploying the SFDC Deduplication Agent API to Railway.app.

---

## 📁 Project Structure

```
sfdc-dedup-agent/
├── main.py                      # FastAPI application entry point
├── requirements.txt             # Python dependencies
├── Procfile                     # Railway process configuration
├── .env.example                 # Environment variable template
├── .gitignore                   # Git ignore rules
├── agent/                       # Agent module
│   ├── __init__.py
│   ├── config.py                # Environment configuration
│   ├── dedup_agent.py           # Agent workflow logic
│   ├── tools.py                 # 7 core tools
│   └── langsmith_wrapper.py     # LangSmith observability
├── reports/                     # Generated reports (gitignored)
└── DEPLOYMENT.md                # This file
```

---

## 🚀 Quick Start - Local Development

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:
```bash
# REQUIRED
SF_USERNAME=your_salesforce_username@example.com
SF_PASSWORD=your_salesforce_password
SF_SECURITY_TOKEN=your_salesforce_security_token
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

# OPTIONAL
LANGCHAIN_API_KEY=lsv2_pt_your-langsmith-key-here
PORT=8000
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

### 3. Run the API Locally

```bash
python main.py
```

Or use uvicorn directly:
```bash
uvicorn main:app --reload --port 8000
```

### 4. Test the API

Open your browser to:
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **Root**: http://localhost:8000/

---

## ☁️ Railway.app Deployment

### Prerequisites

1. **GitHub Account**: Repository must be on GitHub
2. **Railway Account**: Sign up at [railway.app](https://railway.app)
3. **Salesforce Credentials**: Developer or production org
4. **Claude API Key**: From [console.anthropic.com](https://console.anthropic.com)

### Step 1: Prepare Repository

```bash
# Initialize git if not already done
git init

# Add all files
git add .

# Commit
git commit -m "Initial commit - SFDC Dedup Agent API"

# Create GitHub repo and push
git remote add origin https://github.com/YOUR_USERNAME/sfdc-dedup-agent.git
git push -u origin main
```

### Step 2: Create Railway Project

1. Go to [railway.app/new](https://railway.app/new)
2. Click **"Deploy from GitHub repo"**
3. Select your `sfdc-dedup-agent` repository
4. Railway will detect the `Procfile` and configure automatically

### Step 3: Configure Environment Variables

In Railway dashboard, go to **Variables** tab and add:

#### Required Variables

```
SF_USERNAME=your_salesforce_username@example.com
SF_PASSWORD=your_salesforce_password
SF_SECURITY_TOKEN=your_salesforce_security_token
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

#### Optional Variables

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_your-langsmith-key-here
LANGCHAIN_PROJECT=sfdc-dedup-agent
CORS_ORIGINS=https://your-frontend-domain.com
```

**Note:** Railway automatically sets `PORT` and `RAILWAY_ENVIRONMENT=production`.

### Step 4: Deploy

1. Railway will automatically deploy after you add environment variables
2. Watch the deployment logs in real-time
3. Once deployed, Railway provides a public URL: `https://your-app.up.railway.app`

### Step 5: Verify Deployment

Test the health endpoint:

```bash
curl https://your-app.up.railway.app/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-10-05T...",
  "salesforce_connected": true,
  "claude_api_configured": true,
  "langsmith_configured": true
}
```

---

## 📡 API Endpoints

### Health Check
```
GET /health
```

Returns API health status and configuration validation.

### Start Deduplication Job
```
POST /api/dedup/start
Content-Type: application/json

{
  "batch_size": 100,          // Optional: limit contacts
  "owner_filter": ["00G..."],  // Optional: filter by Account Owner IDs
  "auto_approve": false        // Optional: skip human-in-the-loop
}
```

Returns:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Deduplication job started successfully",
  "created_at": "2025-10-05T..."
}
```

### Get Job Status
```
GET /api/dedup/status/{job_id}
```

Returns job progress, metrics, and status.

### List All Jobs
```
GET /api/dedup/jobs
```

Returns list of all jobs.

### Get Pending Approval
```
GET /api/dedup/pending/{job_id}
```

Returns duplicate pairs awaiting human approval.

### Approve/Reject Decision
```
POST /api/dedup/approve
Content-Type: application/json

{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "approved": true,
  "rejected_pairs": []  // Optional: partially approve
}
```

### Get Dashboard Metrics
```
GET /api/dashboard
```

Returns aggregate metrics across all jobs.

### WebSocket - Real-time Updates
```
ws://your-app.up.railway.app/ws/updates/{job_id}
```

Connect with WebSocket client to receive real-time job progress updates.

---

## 🔄 Human-in-the-Loop Workflow

1. **Start Job**: POST to `/api/dedup/start` with `auto_approve: false`
2. **Monitor Progress**: WebSocket connection for real-time updates
3. **Job Pauses**: Status changes to `awaiting_approval`
4. **Get Details**: GET `/api/dedup/pending/{job_id}` to see duplicate pairs
5. **User Reviews**: Frontend shows duplicate pairs for human review
6. **Approve/Reject**: POST to `/api/dedup/approve` with decision
7. **Job Resumes**: Agent continues processing
8. **Second Checkpoint**: Job pauses again before final Salesforce update
9. **Final Approval**: User approves/rejects Salesforce updates
10. **Completion**: Job status changes to `completed`

---

## 🖥️ Frontend Integration Example

### React + WebSocket

```javascript
import { useState, useEffect } from 'react';

function DedupJobMonitor({ jobId }) {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    // Connect to WebSocket
    const ws = new WebSocket(`wss://your-app.up.railway.app/ws/updates/${jobId}`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'job_update') {
        setStatus(data.data);

        // Check if awaiting approval
        if (data.data.status === 'awaiting_approval') {
          fetchPendingApproval(jobId);
        }
      }
    };

    return () => ws.close();
  }, [jobId]);

  return (
    <div>
      <h3>Job Status: {status?.status}</h3>
      <p>{status?.progress?.message}</p>
      <progress value={status?.progress?.current_step} max={status?.progress?.total_steps} />
    </div>
  );
}

// Approve decision
async function approveDecision(jobId, approved) {
  const response = await fetch('https://your-app.up.railway.app/api/dedup/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, approved })
  });

  return response.json();
}
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SF_USERNAME` | ✅ | Salesforce username | - |
| `SF_PASSWORD` | ✅ | Salesforce password | - |
| `SF_SECURITY_TOKEN` | ✅ | Salesforce security token | - |
| `ANTHROPIC_API_KEY` | ✅ | Claude API key | - |
| `LANGCHAIN_API_KEY` | ❌ | LangSmith API key (optional) | - |
| `LANGCHAIN_TRACING_V2` | ❌ | Enable LangSmith tracing | `false` |
| `PORT` | ❌ | Server port (Railway sets this) | `8000` |
| `CORS_ORIGINS` | ❌ | Allowed CORS origins (comma-separated) | `*` |

### CORS Configuration

For production, set specific origins:

```bash
CORS_ORIGINS=https://app.yourdomain.com,https://admin.yourdomain.com
```

For development (all origins):
```bash
CORS_ORIGINS=*
```

---

## 📊 Monitoring & Observability

### LangSmith Integration

1. Sign up at [smith.langchain.com](https://smith.langchain.com/)
2. Create an API key
3. Add to Railway environment variables:
   ```
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=lsv2_pt_your-key-here
   ```

4. View traces in LangSmith dashboard

### Railway Metrics

Railway provides built-in metrics:
- **CPU Usage**
- **Memory Usage**
- **Request Logs**
- **Deployment History**

Access via Railway dashboard → your project → Metrics tab.

---

## 🐛 Troubleshooting

### Health Check Fails

**Symptom**: `/health` returns `degraded` status

**Solution**:
1. Check environment variables are set correctly
2. Verify Salesforce credentials:
   ```bash
   curl https://your-app.up.railway.app/health
   ```
3. Check Railway logs for connection errors

### WebSocket Connection Fails

**Symptom**: WebSocket won't connect

**Solution**:
1. Ensure using `wss://` (not `ws://`) for production
2. Check CORS settings
3. Verify Railway deployment is running

### Job Stuck in "Running" Status

**Symptom**: Job never completes

**Solution**:
1. Check Railway logs for errors
2. Verify Claude API key is valid
3. Check Salesforce connection hasn't timed out
4. Review job error field: `GET /api/dedup/status/{job_id}`

### Out of Memory

**Symptom**: Railway deployment crashes with OOM error

**Solution**:
1. Reduce batch_size in job request
2. Upgrade Railway plan for more memory
3. Process fewer contacts per job

---

## 💰 Cost Estimates

### Railway Costs

- **Hobby Plan**: $5/month (512 MB RAM, limited hours)
- **Pro Plan**: $20/month (8 GB RAM, unlimited hours)

### Claude API Costs

Based on Claude 3.5 Haiku:
- **Cost per contact**: ~$0.00017
- **1,000 contacts**: ~$0.17
- **10,000 contacts**: ~$1.70
- **100,000 contacts**: ~$17.00

**Recommendation**: Start with Hobby plan + small batches, upgrade as needed.

---

## 🔐 Security Best Practices

1. **Never commit `.env` file** - use `.env.example` instead
2. **Use Railway environment variables** for production secrets
3. **Set specific CORS origins** in production
4. **Rotate API keys regularly**
5. **Monitor API usage** via LangSmith and Railway logs
6. **Use HTTPS only** for production APIs

---

## 🔄 Updating the Deployment

```bash
# Make changes locally
git add .
git commit -m "Your changes"
git push origin main
```

Railway will automatically detect the push and redeploy.

---

## 📚 Additional Resources

- **FastAPI Docs**: https://fastapi.tiangolo.com
- **Railway Docs**: https://docs.railway.app
- **Claude API Docs**: https://docs.anthropic.com
- **LangSmith Docs**: https://docs.smith.langchain.com

---

## 🆘 Support

For issues related to:
- **Agent Logic**: Review [SYSTEM_DOCUMENTATION.md](SYSTEM_DOCUMENTATION.md)
- **LangSmith**: Review [LANGSMITH_SETUP.md](LANGSMITH_SETUP.md)
- **Deployment**: Check Railway logs and this guide

---

## ✅ Deployment Checklist

- [ ] Repository pushed to GitHub
- [ ] Railway project created
- [ ] Environment variables set in Railway
- [ ] Deployment successful (check logs)
- [ ] Health check returns `healthy`
- [ ] Test job started successfully
- [ ] WebSocket connection works
- [ ] Frontend integrated (if applicable)
- [ ] LangSmith tracing enabled (optional)
- [ ] CORS configured for your domain
- [ ] Monitoring set up

---

**You're ready to deploy!** 🚀

Need help? Open an issue on GitHub or check the Railway community forum.
