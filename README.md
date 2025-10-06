# SFDC Deduplication Agent - Production API

AI-powered Salesforce contact deduplication with human-in-the-loop approval, deployed on Railway.app.

🚀 **[Deploy to Railway](https://railway.app/new)** | 📚 **[API Docs](#api-documentation)** | 🔧 **[Configuration](#configuration)**

---

## Features

- ✅ **AI-Powered Duplicate Detection** using Claude 3.5
- ✅ **Human-in-the-Loop Approval** for merge decisions
- ✅ **Real-time Progress** via WebSocket
- ✅ **Email Validation** using Salesforce activity history
- ✅ **Batch Processing** by Account Owner
- ✅ **Cost Tracking** with LangSmith integration
- ✅ **Production-Ready** FastAPI backend
- ✅ **Railway Deployment** with one click

---

## Quick Start

### Local Development

1. **Clone & Install**
   ```bash
   git clone https://github.com/YOUR_USERNAME/sfdc-dedup-agent.git
   cd sfdc-dedup-agent
   pip install -r requirements.txt
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Run API Server**
   ```bash
   python main.py
   ```

4. **Test API**
   ```bash
   python test_api.py
   ```

5. **Open Docs**
   - API Docs: http://localhost:8000/docs
   - Health Check: http://localhost:8000/health

### Production Deployment

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for complete Railway deployment instructions.

---

## API Documentation

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check and config validation |
| `/api/dedup/start` | POST | Start a deduplication job |
| `/api/dedup/status/:job_id` | GET | Get job status and progress |
| `/api/dedup/pending/:job_id` | GET | Get duplicate pairs awaiting approval |
| `/api/dedup/approve` | POST | Approve/reject merge decision |
| `/api/dashboard` | GET | Get aggregate metrics |
| `/ws/updates/:job_id` | WebSocket | Real-time job updates |

**Full API documentation:** http://localhost:8000/docs (when running)

---

## How It Works

### Workflow

```
1. Start Job
   POST /api/dedup/start
   ↓
2. Extract Contacts
   Groups by Account Owner
   ↓
3. Validate Emails
   Check bounce status + activity
   ↓
4. Detect Duplicates
   Claude AI analyzes contacts
   ↓
5. Human Approval ⏸️
   GET /api/dedup/pending/:job_id
   POST /api/dedup/approve
   ↓
6. Update Salesforce
   Batch update contacts
   ↓
7. Generate Reports
   Markdown + JSON + Dashboard
```

### Human-in-the-Loop

Jobs pause at two checkpoints for human approval:

1. **Duplicate Marking**: Review AI-detected duplicates before marking
2. **Salesforce Update**: Final approval before updating records

Frontend can:
- Connect via WebSocket for real-time updates
- Fetch pending approvals via REST API
- Submit approve/reject decisions
- Monitor progress and view reports

---

## Configuration

### Required Environment Variables

```bash
SF_USERNAME=your_salesforce_username@example.com
SF_PASSWORD=your_salesforce_password
SF_SECURITY_TOKEN=your_salesforce_security_token
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

### Optional Environment Variables

```bash
LANGCHAIN_API_KEY=lsv2_pt_your-key-here  # LangSmith observability
PORT=8000                                  # Server port
CORS_ORIGINS=https://app.example.com       # CORS allowed origins
```

See [.env.example](.env.example) for complete template.

---

## Project Structure

```
sfdc-dedup-agent/
├── main.py                 # FastAPI app + WebSocket
├── requirements.txt        # Dependencies
├── Procfile               # Railway configuration
├── .env.example           # Environment template
├── agent/                 # Agent module
│   ├── config.py          # Config management
│   ├── dedup_agent.py     # Workflow runner
│   ├── tools.py           # 7 core tools
│   └── langsmith_wrapper.py
├── reports/               # Generated reports (gitignored)
├── test_api.py            # API test suite
├── DEPLOYMENT.md          # Railway deployment guide
└── README.md              # This file
```

---

## Cost Estimates

### API Usage

- **Claude API** (Haiku 3.5):
  - ~$0.00017 per contact
  - ~$0.17 per 1,000 contacts
  - ~$17 per 100,000 contacts

- **Railway Hosting**:
  - Hobby: $5/month (512 MB RAM)
  - Pro: $20/month (8 GB RAM)

### Optimization Tips

1. Use `batch_size` to limit contacts per job
2. Filter by `owner_filter` for specific Account Owners
3. Monitor costs via LangSmith dashboard
4. Start small, scale as needed

---

## Frontend Integration

### React Example

```javascript
// Start a job
const response = await fetch('https://your-app.up.railway.app/api/dedup/start', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    batch_size: 100,
    auto_approve: false
  })
});

const { job_id } = await response.json();

// Connect to WebSocket for updates
const ws = new WebSocket(`wss://your-app.up.railway.app/ws/updates/${job_id}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === 'job_update') {
    console.log('Progress:', data.data.progress);

    if (data.data.status === 'awaiting_approval') {
      // Fetch pending approvals
      fetchPendingApprovals(job_id);
    }
  }
};

// Approve decision
await fetch('https://your-app.up.railway.app/api/dedup/approve', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    job_id,
    approved: true
  })
});
```

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for more examples.

---

## Testing

### Run Test Suite

```bash
# Start server
python main.py

# In another terminal
python test_api.py
```

### Manual Testing

```bash
# Health check
curl http://localhost:8000/health

# Start job
curl -X POST http://localhost:8000/api/dedup/start \
  -H "Content-Type: application/json" \
  -d '{"batch_size": 10, "auto_approve": true}'

# Get job status
curl http://localhost:8000/api/dedup/status/JOB_ID
```

---

## Monitoring

### LangSmith Integration

Track all Claude API calls, costs, and performance:

1. Sign up at [smith.langchain.com](https://smith.langchain.com/)
2. Get API key
3. Add to environment:
   ```bash
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=lsv2_pt_your-key-here
   ```
4. View traces in LangSmith dashboard

### Railway Metrics

- CPU/Memory usage
- Request logs
- Deployment history
- Custom alerts

---

## Security

- ✅ Environment variables for secrets
- ✅ CORS protection
- ✅ HTTPS only (Railway provides SSL)
- ✅ API key validation
- ✅ Input sanitization

**Never commit `.env` file!**

---

## Troubleshooting

### API won't start

- Check environment variables are set
- Verify Python 3.11+ is installed
- Install dependencies: `pip install -r requirements.txt`

### Salesforce connection fails

- Verify credentials in `.env`
- Check security token is correct
- Test health endpoint: `/health`

### WebSocket won't connect

- Use `wss://` for production (not `ws://`)
- Check CORS settings
- Verify Railway deployment is running

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for more troubleshooting.

---

## Documentation

- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Railway deployment guide
- **[LANGSMITH_SETUP.md](LANGSMITH_SETUP.md)** - Observability setup
- **[SYSTEM_DOCUMENTATION.md](SYSTEM_DOCUMENTATION.md)** - Agent logic
- **[AGENT_DESIGN.md](AGENT_DESIGN.md)** - Architecture

---

## Support

- **Issues**: [GitHub Issues](https://github.com/YOUR_USERNAME/sfdc-dedup-agent/issues)
- **Discussions**: [GitHub Discussions](https://github.com/YOUR_USERNAME/sfdc-dedup-agent/discussions)
- **Railway**: [Railway Community](https://railway.app/help)

---

## License

MIT License - see LICENSE file for details.

---

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

**Built with ❤️ using FastAPI, Claude AI, and Railway**
