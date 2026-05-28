## Component Plan

### Scope

- Standalone module for bench-resource-to-job matching and apply packet preparation.
- No direct dependency on existing frontend/backend services.

### Stage 1 (Completed)

- Bench resource and job data models
- Match scoring with configurable threshold
- Resume optimization drafting with truthfulness guardrails
- Cover letter generation
- Audit activity logger
- CLI runner and sample input
- FastAPI wrapper with endpoints for matching, packet preparation, and activity log retrieval
- File-upload endpoint for JobSpy CSV input
- Extension handoff contract endpoint for user-confirmed apply flow
- Standalone scheduler runner for recurring processing windows
- Grouped apply packet endpoint (candidate-wise sorted output)
- Portal adapter contract definitions (LinkedIn and Indeed)
- Optional scheduler webhook callback for run summaries
- Extension task queue endpoint for adapter execution orchestration
- One-shot file-upload endpoint to produce extension queue in a single call
- Adzuna adapter component with job search + candidate matching endpoints

### Stage 2 (Next)

- Adapter-facing output schema for browser extension actions
- Per-portal field map registry
- Rejection and retry reason taxonomy
- Packet signing/hash for tamper-evident audit

### Stage 3 (Later)

- FastAPI wrapper service for UI/backend integration
- AuthN/AuthZ and tenant isolation
- Scheduler for rolling 24-48 hour ingestion cycles
- Analytics dashboard metrics
