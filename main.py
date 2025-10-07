"""
FastAPI wrapper for SFDC Deduplication Agent
Provides REST API and WebSocket endpoints for production deployment on Railway.app
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# Pydantic Models
# ============================================================================

class StartJobRequest(BaseModel):
    batch_size: Optional[int] = Field(None, description="Limit number of contacts to process")
    owner_filter: Optional[List[str]] = Field(None, description="Filter by specific Account Owner IDs")
    auto_approve: bool = Field(False, description="Auto-approve all decisions (skip human-in-the-loop)")

class StartJobResponse(BaseModel):
    job_id: str
    status: str
    message: str
    created_at: str

class JobStatus(BaseModel):
    job_id: str
    status: str  # pending, running, awaiting_approval, completed, failed, cancelled
    progress: Dict[str, Any]
    metrics: Dict[str, Any]
    created_at: str
    updated_at: str
    error: Optional[str] = None

class DuplicatePair(BaseModel):
    pair_id: str
    account_name: str
    confidence: str
    reasoning: str
    canonical_name: str
    contact_1: Dict[str, Any]
    contact_2: Dict[str, Any]

class PendingApproval(BaseModel):
    job_id: str
    stage: str  # "duplicate_marking" or "salesforce_update"
    total_updates: int
    duplicate_pairs: List[DuplicatePair]
    message: str

class ApprovalRequest(BaseModel):
    job_id: str
    approved: bool
    rejected_pairs: Optional[List[str]] = Field(None, description="IDs of pairs to reject if partially approving")

class ApprovalResponse(BaseModel):
    job_id: str
    status: str
    message: str

class DashboardMetrics(BaseModel):
    total_jobs: int
    active_jobs: int
    completed_jobs: int
    failed_jobs: int
    total_contacts_processed: int
    total_duplicates_found: int
    total_cost: float
    last_updated: str

class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    salesforce_connected: bool
    claude_api_configured: bool
    langsmith_configured: bool

# ============================================================================
# Job State Management (In-Memory)
# ============================================================================

class JobManager:
    """Manages job state and lifecycle"""

    def __init__(self):
        self.jobs: Dict[str, Dict] = {}
        self.websocket_clients: Dict[str, List[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def create_job(self, config: StartJobRequest) -> str:
        """Create a new job"""
        job_id = str(uuid.uuid4())

        async with self.lock:
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "pending",
                "config": config.dict(),
                "progress": {
                    "phase": "initializing",
                    "current_step": 0,
                    "total_steps": 7,
                    "message": "Job created"
                },
                "metrics": {
                    "total_contacts": 0,
                    "total_owners": 0,
                    "emails_validated": 0,
                    "duplicates_found": 0,
                    "sfdc_updates": 0
                },
                "phase_details": {
                    # Stores detailed data for each completed phase
                    # e.g. "phase_1_connect": {...}, "phase_2_extract": {...}
                },
                "pending_approval": None,
                "results": None,
                "error": None,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            self.websocket_clients[job_id] = []

        logger.info(f"Created job {job_id}")
        return job_id

    async def update_job(self, job_id: str, updates: Dict):
        """Update job state"""
        async with self.lock:
            if job_id not in self.jobs:
                raise ValueError(f"Job {job_id} not found")

            self.jobs[job_id].update(updates)
            self.jobs[job_id]["updated_at"] = datetime.now().isoformat()

        # Notify WebSocket clients
        await self.broadcast_update(job_id, self.jobs[job_id])

    async def get_job(self, job_id: str) -> Optional[Dict]:
        """Get job state"""
        async with self.lock:
            return self.jobs.get(job_id)

    async def list_jobs(self) -> List[Dict]:
        """List all jobs"""
        async with self.lock:
            return list(self.jobs.values())

    async def add_websocket(self, job_id: str, websocket: WebSocket):
        """Add WebSocket client for job updates"""
        async with self.lock:
            if job_id not in self.websocket_clients:
                self.websocket_clients[job_id] = []
            self.websocket_clients[job_id].append(websocket)

    async def remove_websocket(self, job_id: str, websocket: WebSocket):
        """Remove WebSocket client"""
        async with self.lock:
            if job_id in self.websocket_clients:
                try:
                    self.websocket_clients[job_id].remove(websocket)
                except ValueError:
                    pass

    async def broadcast_update(self, job_id: str, data: Dict):
        """Broadcast update to all WebSocket clients for this job"""
        if job_id not in self.websocket_clients:
            return

        # Create a copy of the client list to avoid modification during iteration
        async with self.lock:
            clients = self.websocket_clients[job_id].copy()

        message = json.dumps({
            "type": "job_update",
            "job_id": job_id,
            "data": data
        })

        for websocket in clients:
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.error(f"Error sending WebSocket message: {e}")
                await self.remove_websocket(job_id, websocket)

# Initialize job manager
job_manager = JobManager()

# ============================================================================
# Agent Runner (Async wrapper around existing agent)
# ============================================================================

async def run_agent_job(job_id: str):
    """
    Run the deduplication agent asynchronously.
    This is a wrapper that will call your existing agent code.
    """
    try:
        job = await job_manager.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        config = job["config"]

        # Update status to running
        await job_manager.update_job(job_id, {
            "status": "running",
            "progress": {
                "phase": "phase_1_connect",
                "current_step": 1,
                "total_steps": 7,
                "message": "Connecting to Salesforce..."
            }
        })

        # Import agent here to avoid circular imports
        from agent.dedup_agent import run_agent_workflow

        # Run the agent workflow in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            run_agent_workflow,
            job_id,
            config,
            job_manager  # Pass job_manager for progress updates
        )

        # Update job with results
        await job_manager.update_job(job_id, {
            "status": "completed",
            "results": result,
            "progress": {
                "phase": "completed",
                "current_step": 7,
                "total_steps": 7,
                "message": "Job completed successfully"
            }
        })

        logger.info(f"Job {job_id} completed successfully")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}", exc_info=True)
        await job_manager.update_job(job_id, {
            "status": "failed",
            "error": str(e),
            "progress": {
                "phase": "failed",
                "message": f"Job failed: {str(e)}"
            }
        })

# ============================================================================
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Startup
    logger.info("Starting SFDC Deduplication Agent API")
    logger.info(f"Environment: {os.getenv('RAILWAY_ENVIRONMENT', 'local')}")

    yield

    # Shutdown
    logger.info("Shutting down SFDC Deduplication Agent API")

app = FastAPI(
    title="SFDC Deduplication Agent API",
    description="AI-powered Salesforce contact deduplication with human-in-the-loop approval",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for Railway and monitoring"""

    # Check Salesforce credentials
    sf_configured = all([
        os.getenv("SF_USERNAME"),
        os.getenv("SF_PASSWORD"),
        os.getenv("SF_SECURITY_TOKEN")
    ])

    # Check Claude API
    claude_configured = bool(os.getenv("ANTHROPIC_API_KEY"))

    # Check LangSmith (optional)
    langsmith_configured = bool(os.getenv("LANGCHAIN_API_KEY"))

    # Try to connect to Salesforce
    sf_connected = False
    if sf_configured:
        try:
            from agent.tools import test_salesforce_connection
            sf_connected = await asyncio.get_event_loop().run_in_executor(
                None, test_salesforce_connection
            )
        except Exception as e:
            logger.warning(f"Salesforce connection test failed: {e}")

    return HealthResponse(
        status="healthy" if sf_configured and claude_configured else "degraded",
        version="1.0.0",
        timestamp=datetime.now().isoformat(),
        salesforce_connected=sf_connected,
        claude_api_configured=claude_configured,
        langsmith_configured=langsmith_configured
    )

@app.post("/api/dedup/start", response_model=StartJobResponse)
async def start_dedup_job(request: StartJobRequest, background_tasks: BackgroundTasks):
    """Start a new deduplication job"""

    try:
        # Create job
        job_id = await job_manager.create_job(request)

        # Run agent in background
        background_tasks.add_task(run_agent_job, job_id)

        return StartJobResponse(
            job_id=job_id,
            status="pending",
            message="Deduplication job started successfully",
            created_at=datetime.now().isoformat()
        )

    except Exception as e:
        logger.error(f"Failed to start job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start job: {str(e)}")

@app.get("/api/dedup/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get status of a deduplication job"""

    job = await job_manager.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobStatus(
        job_id=job["job_id"],
        status=job["status"],
        progress=job["progress"],
        metrics=job["metrics"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        error=job.get("error")
    )

@app.get("/api/dedup/jobs")
async def list_jobs():
    """List all jobs"""
    jobs = await job_manager.list_jobs()
    return {"jobs": jobs}

@app.get("/api/dedup/{job_id}/phase/{phase_name}")
async def get_phase_details(job_id: str, phase_name: str):
    """Get detailed data for a specific phase of a job"""
    job = await job_manager.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    phase_details = job.get("phase_details", {})

    if phase_name not in phase_details:
        raise HTTPException(
            status_code=404,
            detail=f"Phase '{phase_name}' not found or not yet completed"
        )

    return {
        "job_id": job_id,
        "phase": phase_name,
        "details": phase_details[phase_name],
        "timestamp": phase_details[phase_name].get("timestamp")
    }

@app.post("/api/dedup/approve", response_model=ApprovalResponse)
async def approve_decision(request: ApprovalRequest):
    """Approve or reject a human-in-the-loop decision"""

    job = await job_manager.get_job(request.job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {request.job_id} not found")

    if job["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not awaiting approval (current status: {job['status']})"
        )

    # Store approval decision
    await job_manager.update_job(request.job_id, {
        "approval_decision": {
            "approved": request.approved,
            "rejected_pairs": request.rejected_pairs or [],
            "timestamp": datetime.now().isoformat()
        },
        "status": "running"  # Resume job
    })

    return ApprovalResponse(
        job_id=request.job_id,
        status="approved" if request.approved else "rejected",
        message=f"Decision {'approved' if request.approved else 'rejected'} successfully"
    )

@app.get("/api/dedup/pending/{job_id}", response_model=PendingApproval)
async def get_pending_approval(job_id: str):
    """Get pending approval details for a job"""

    job = await job_manager.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Check if there's pending_approval data
    approval_data = job.get("pending_approval")

    # If no pending_approval, try to get duplicate pairs from phase_details
    if not approval_data or not approval_data.get("decisions"):
        phase_details = job.get("phase_details", {})
        phase_4_data = phase_details.get("phase_4_detect", {})

        if phase_4_data and phase_4_data.get("duplicate_pairs"):
            # Convert phase_4 duplicate pairs to the format expected for approval
            # Phase 4 format: {contact_id_1, contact_id_2, confidence, reasoning, account_name}
            # Need to transform to: {contact_1: {id, name, email}, contact_2: {...}}

            # Get contact details from phase_2
            phase_2_data = phase_details.get("phase_2_extract", {})
            contacts_list = phase_2_data.get("contacts", [])
            contacts_by_id = {c["id"]: c for c in contacts_list}

            # Also create case-insensitive prefix lookup for Salesforce ID variations
            # SFDC IDs can be 15 or 18 chars, case variations exist
            contacts_by_prefix = {}
            for c in contacts_list:
                # Use first 15 chars (case-insensitive) as key
                prefix = c["id"][:15].upper()
                contacts_by_prefix[prefix] = c

            def find_contact(contact_id):
                """Find contact by ID, trying exact match then prefix match"""
                # Try exact match first
                if contact_id in contacts_by_id:
                    return contacts_by_id[contact_id]
                # Try prefix match (first 15 chars, case-insensitive)
                prefix = contact_id[:15].upper() if contact_id else ""
                return contacts_by_prefix.get(prefix, {})

            duplicate_pairs = []
            for pair in phase_4_data["duplicate_pairs"]:
                contact_1_id = pair.get("contact_id_1")
                contact_2_id = pair.get("contact_id_2")

                contact_1_data = find_contact(contact_1_id)
                contact_2_data = find_contact(contact_2_id)

                duplicate_pairs.append(DuplicatePair(
                    pair_id=f"{contact_1_id}_{contact_2_id}",
                    account_name=pair.get("account_name", "Unknown"),
                    confidence=pair.get("confidence", "unknown"),
                    reasoning=pair.get("reasoning", ""),
                    canonical_name=pair.get("canonical_name", ""),
                    contact_1={
                        "id": contact_1_id,
                        "name": contact_1_data.get("name", "Unknown"),
                        "email": contact_1_data.get("email", ""),
                        "phone": contact_1_data.get("phone", ""),
                        "title": contact_1_data.get("title", "")
                    },
                    contact_2={
                        "id": contact_2_id,
                        "name": contact_2_data.get("name", "Unknown"),
                        "email": contact_2_data.get("email", ""),
                        "phone": contact_2_data.get("phone", ""),
                        "title": contact_2_data.get("title", "")
                    }
                ))

            return PendingApproval(
                job_id=job_id,
                stage="duplicate_review",
                total_updates=len(duplicate_pairs),
                duplicate_pairs=duplicate_pairs,
                message=f"Found {len(duplicate_pairs)} duplicate pair(s) for review"
            )

        # No duplicates found anywhere
        raise HTTPException(
            status_code=404,
            detail=f"No pending approval or duplicates found for job {job_id}"
        )

    # Standard path: use pending_approval data with decisions
    duplicate_pairs = [
        DuplicatePair(
            pair_id=f"{d['contact_1']['id']}_{d['contact_2']['id']}",
            account_name=d.get("account_name", "Unknown"),
            confidence=d.get("confidence", "unknown"),
            reasoning=d.get("reasoning", ""),
            canonical_name=d.get("canonical_name", ""),
            contact_1=d["contact_1"],
            contact_2=d["contact_2"]
        )
        for d in approval_data.get("decisions", [])
    ]

    return PendingApproval(
        job_id=job_id,
        stage=approval_data.get("stage", "unknown"),
        total_updates=approval_data.get("total_updates", 0),
        duplicate_pairs=duplicate_pairs,
        message=approval_data.get("message", "")
    )

@app.get("/api/dashboard", response_model=DashboardMetrics)
async def get_dashboard_metrics():
    """Get dashboard metrics across all jobs"""

    jobs = await job_manager.list_jobs()

    total_contacts = sum(j["metrics"].get("total_contacts", 0) for j in jobs)
    total_duplicates = sum(j["metrics"].get("duplicates_found", 0) for j in jobs)

    # Calculate total cost from job results
    total_cost = 0.0
    for job in jobs:
        if job.get("results") and job["results"].get("cost_summary"):
            total_cost += job["results"]["cost_summary"].get("total_cost", 0.0)

    return DashboardMetrics(
        total_jobs=len(jobs),
        active_jobs=len([j for j in jobs if j["status"] in ["pending", "running", "awaiting_approval"]]),
        completed_jobs=len([j for j in jobs if j["status"] == "completed"]),
        failed_jobs=len([j for j in jobs if j["status"] == "failed"]),
        total_contacts_processed=total_contacts,
        total_duplicates_found=total_duplicates,
        total_cost=total_cost,
        last_updated=datetime.now().isoformat()
    )

@app.websocket("/ws/updates/{job_id}")
async def websocket_updates(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job updates"""

    await websocket.accept()
    await job_manager.add_websocket(job_id, websocket)

    try:
        # Send initial job state
        job = await job_manager.get_job(job_id)
        if job:
            await websocket.send_text(json.dumps({
                "type": "initial_state",
                "job_id": job_id,
                "data": job
            }))

        # Keep connection alive and listen for client messages
        while True:
            data = await websocket.receive_text()
            # Echo back (can be used for heartbeat)
            await websocket.send_text(json.dumps({
                "type": "pong",
                "timestamp": datetime.now().isoformat()
            }))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job {job_id}")
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
    finally:
        await job_manager.remove_websocket(job_id, websocket)

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "SFDC Deduplication Agent API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/debug/env")
async def debug_env():
    """Debug endpoint to check environment variables (REMOVE IN PRODUCTION!)"""
    return {
        "SF_USERNAME_set": bool(os.getenv("SF_USERNAME")),
        "SF_PASSWORD_set": bool(os.getenv("SF_PASSWORD")),
        "SF_SECURITY_TOKEN_set": bool(os.getenv("SF_SECURITY_TOKEN")),
        "ANTHROPIC_API_KEY_set": bool(os.getenv("ANTHROPIC_API_KEY")),
        "LANGCHAIN_API_KEY_set": bool(os.getenv("LANGCHAIN_API_KEY")),
        "PORT": os.getenv("PORT"),
        "RAILWAY_ENVIRONMENT": os.getenv("RAILWAY_ENVIRONMENT"),
        "env_var_count": len(os.environ)
    }

# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now().isoformat()
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc),
            "timestamp": datetime.now().isoformat()
        }
    )

# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("RAILWAY_ENVIRONMENT") != "production"
    )
