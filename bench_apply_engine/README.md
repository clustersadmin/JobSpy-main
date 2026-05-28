## Bench Apply Engine (Standalone Component)

This is a separate component built to integrate with existing bench resource systems later.
It does not modify the current frontend or backend.

### Purpose

Given:
- Bench resources (profiles + verified skills + base resume)
- JobSpy output CSV

It produces:
- Match-qualified jobs (threshold default 70%)
- Truthfulness-safe optimized resume drafts (no fabricated skills/experience)
- Cover letter drafts
- Apply packets for extension-based submit flow
- Activity logs (JSONL) for audit trail

### Inputs

1. `bench_resources.json`
- Candidate profile list
- Verified skills
- Base resume text

2. JobSpy CSV
- Works with current user-facing exports (`Title`, `Portal`, `Job Location`, `Job Description Version 1`, etc.)

### Run

```bash
cd bench_apply_engine
python main.py --bench-json bench_resources.sample.json --jobs-csv ..\outputs\extracted_details_check_v2.csv --output-dir component_outputs --threshold 70
```

### FastAPI Wrapper (for later UI/backend integration)

Install API dependencies:

```bash
cd bench_apply_engine
pip install -r requirements.txt
```

Run API:

```bash
cd bench_apply_engine
python run_api.py
```

Base URL: `http://localhost:8011`

Endpoints:

- `GET /health`
- `GET /adzuna/credentials-status`
- `POST /adzuna/search-jobs`
- `POST /candidate-match-from-jd`
- `POST /adzuna/search-and-match`
- `POST /match-jobs`
- `POST /prepare-apply-packets`
- `POST /prepare-apply-packets-grouped` (grouped by candidate, sorted by score)
- `POST /prepare-apply-packets-from-files` (multipart: resources_json + jobs_csv)
- `POST /activity-log`
- `POST /extension-handoff`
- `GET /extension-adapter/{portal}` (adapter contract, e.g. linkedin/indeed)
- `POST /extension-task-queue` (build extension execution queue from grouped packets)
- `POST /extension-task-queue-from-files` (one-shot: upload resources + jobs CSV and return queue)

Example request payload (for `match-jobs` or `prepare-apply-packets`):

```json
{
	"threshold": 70,
	"resources": [
		{
			"resource_id": "bench-001",
			"full_name": "Candidate One",
			"target_roles": ["Senior Java Developer"],
			"position_types": ["Contract"],
			"preferred_locations": ["Florida", "Remote"],
			"work_authorization": "H1B Transfer",
			"expected_rate": "$65/hr",
			"verified_skills": ["Java", "Spring Boot", "AWS"],
			"base_resume_text": "Senior Java developer with Spring Boot and AWS background."
		}
	],
	"jobs": [
		{
			"job_id": "job-1001",
			"title": "Senior Java Developer",
			"portal": "linkedin",
			"location": "Jacksonville FL",
			"job_type": "Contract",
			"job_description": "Need Spring Boot, AWS, REST API, SQL",
			"salary_or_rate": "$65/hr",
			"immigration_status": "Sponsorship/Work Visa Mentioned",
			"url": "https://example.com/job-1001"
		}
	]
}
```

Example multipart call for `prepare-apply-packets-from-files`:

```bash
curl -X POST http://localhost:8011/prepare-apply-packets-from-files \
	-F "resources_json=[{\"resource_id\":\"bench-001\",\"full_name\":\"Candidate One\",\"target_roles\":[\"Senior Java Developer\"],\"position_types\":[\"Contract\"],\"preferred_locations\":[\"Florida\"],\"work_authorization\":\"H1B Transfer\",\"verified_skills\":[\"Java\",\"Spring Boot\"],\"base_resume_text\":\"Senior Java developer profile\"}]" \
	-F "threshold=70" \
	-F "output_dir=component_outputs" \
	-F "jobs_csv=@sample_jobs.csv"
```

Extension handoff contract:

- Send one `apply_packet` from output packets to `POST /extension-handoff`
- Response returns ordered actions for extension prefill flow with human-confirm submit guardrail

Grouped packet response:

- Use `POST /prepare-apply-packets-grouped`
- Returns `resources` object where each key is `resource_id`
- Packets are sorted by `match_score` descending for quick UI ranking

Portal adapter contracts:

- `GET /extension-adapter/linkedin`
- `GET /extension-adapter/indeed`
- Contract JSON contains steps, selectors, and guardrails for extension implementation

Extension task queue:

- Use `POST /extension-task-queue` with `grouped_packets` from `prepare-apply-packets-grouped`
- Supports `resource_id`, `max_tasks_per_resource`, and `cooldown_seconds`
- Returns ordered task list for browser extension execution with user-confirm submit policy

One-shot queue from files:

- Use `POST /extension-task-queue-from-files` with `resources_json` and `jobs_csv`
- Endpoint internally performs matching, packet preparation, grouping, and queue generation
- Writes:
	- `apply_packets_grouped.json`
	- `extension_task_queue.json`
	- `application_events.jsonl`

Example multipart call:

```bash
curl -X POST http://localhost:8011/extension-task-queue-from-files \
	-F "resources_json=[{\"resource_id\":\"bench-001\",\"full_name\":\"Candidate One\",\"target_roles\":[\"Senior Java Developer\"],\"position_types\":[\"Contract\"],\"preferred_locations\":[\"Florida\"],\"work_authorization\":\"H1B Transfer\",\"verified_skills\":[\"Java\",\"Spring Boot\",\"AWS\"],\"base_resume_text\":\"Senior Java developer with Spring Boot and AWS\"}]" \
	-F "threshold=70" \
	-F "resource_id=bench-001" \
	-F "max_tasks_per_resource=5" \
	-F "cooldown_seconds=120" \
	-F "require_user_confirmation=true" \
	-F "output_dir=component_outputs" \
	-F "jobs_csv=@sample_jobs.csv"
```

Example request:

```json
{
	"grouped_packets": {
		"resources": {
			"bench-001": [
				{
					"resource_id": "bench-001",
					"job_id": "job-1001",
					"portal": "linkedin",
					"title": "Senior Java Developer",
					"location": "Florida",
					"match_score": 83.4,
					"optimized_resume_text": "...",
					"cover_letter_text": "..."
				}
			]
		}
	},
	"resource_id": "bench-001",
	"max_tasks_per_resource": 5,
	"cooldown_seconds": 120,
	"require_user_confirmation": true
}
```

### Scheduler (24-48h style recurring runs)

Single run (safe default):

```bash
cd bench_apply_engine
python run_scheduler.py --bench-json bench_resources.sample.json --jobs-csv sample_jobs.csv --output-dir component_outputs --threshold 70 --interval-minutes 120 --max-runs 1
```

Continuous mode:

```bash
cd bench_apply_engine
python run_scheduler.py --bench-json bench_resources.sample.json --jobs-csv sample_jobs.csv --output-dir component_outputs --threshold 70 --interval-minutes 120 --max-runs 0
```

With webhook callback:

```bash
cd bench_apply_engine
python run_scheduler.py --bench-json bench_resources.sample.json --jobs-csv sample_jobs.csv --output-dir component_outputs --threshold 70 --interval-minutes 120 --max-runs 1 --webhook-url https://your-backend.example.com/api/bench-apply/runs --webhook-timeout-seconds 15
```

Scheduler output:

- `component_outputs/scheduler_runs.jsonl`

### Outputs

- `component_outputs/apply_packets.json`
- `component_outputs/application_events.jsonl`

### Integration Contract (for UI later)

1. Trigger job matching:
- call component with latest bench profiles and latest 24-48h JobSpy CSV

2. Show shortlist:
- read `apply_packets.json`

3. Apply action:
- UI extension uses packet payload for prefill
- user confirms final submit

4. Full traceability:
- read `application_events.jsonl`

### Guardrails

- No hidden bulk apply behavior
- No fabricated resume claims
- Human confirmation required before final submission in portal extension flow

### Adzuna Candidate-Matching Component

Adzuna public API is primarily job listings/data focused. This component supports:

1. Pull jobs from Adzuna (when API credentials are provided).
2. Match your bench candidates to a given job description.
3. Combine both in one flow (`/adzuna/search-and-match`).

Set environment variables:

```bash
set ADZUNA_APP_ID=your_app_id
set ADZUNA_APP_KEY=your_app_key
set ADZUNA_COUNTRY=us
```

Country notes:

- `us` is the Adzuna country code for United States.
- Inputs like `USA` and `United States` are accepted and normalized to `us` automatically.

Quick checks:

- `GET /adzuna/credentials-status`
- `POST /candidate-match-from-jd` with your resources + JD text

`POST /adzuna/search-and-match` options:

- `threshold`: strict match threshold for `rows`
- `near_match_min_score`: minimum score for fallback near matches
- `compact_response`: when `true`, returns UI-friendly compact payload

Compact request example:

```json
{
	"resources": [
		{
			"resource_id": "bench-001",
			"full_name": "Candidate One",
			"target_roles": ["Senior Java Developer"],
			"position_types": ["Contract"],
			"preferred_locations": ["Florida", "Remote"],
			"work_authorization": "H1B Transfer",
			"expected_rate": "$65/hr",
			"verified_skills": ["Java", "Spring Boot", "Microservices", "AWS", "SQL", "REST API", "Kafka"],
			"base_resume_text": "Senior Java Developer profile"
		}
	],
	"query": "java developer",
	"location": "Florida",
	"results_per_page": 5,
	"max_days_old": 7,
	"threshold": 70,
	"near_match_min_score": 20,
	"compact_response": true
}
```

If Adzuna keys are not set, JD-to-candidate matching still works via `/candidate-match-from-jd` without any external API call.
