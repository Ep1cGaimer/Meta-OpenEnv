---
title: Incident Response Environment
emoji: 🚨
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 8000
pinned: false
---
# Production Incident Response — OpenEnv Environment

A deterministic, scored environment for evaluating whether AI agents can effectively respond to production incidents: investigate cascading failures, identify root causes, apply correct remediations, and resolve under SLA pressure.

## Overview

The agent acts as an **on-call Site Reliability Engineer (SRE)** responding to a live production incident across a **10-service microservice architecture**. The environment is **partially observable** — the agent sees alerting services but must actively investigate (check logs, query metrics, trace dependencies) to discover the root cause.

Unlike static evaluation benchmarks, this environment features **dynamic cascading failures**: uninvestigated and unfixed issues propagate to dependent services over time, increasing customer impact and making the problem harder to resolve.

### Why This Environment Matters

Production incident response is a **daily reality** at every technology company. On-call engineers must:
- Triage alerts under time pressure
- Distinguish symptoms from root causes
- Choose the correct fix (rollback vs. restart vs. scale)
- Communicate with stakeholders throughout

This is a genuine **sequential decision-making** problem — not a classification task. The optimal action at step 5 depends on what was discovered at steps 1–4, and the environment state changes whether or not the agent acts.

### Progressive Difficulty

| Level | Scenario | Key Challenge |
|-------|---------|---------------|
| Easy | Bad deploy on payment-service | Follow obvious alerts → rollback |
| Medium | DB connection leak from user-service | Symptoms appear at DB, root cause is 2 hops upstream |
| Hard | Two simultaneous failures (traffic spike + bad deploy) | Must identify and fix BOTH independent root causes |
| Frontier | Silent cache corruption with misleading symptoms | Cache looks healthy on all metrics; only log analysis reveals the truth |

## Action Space (9 types)

| Action | Format | Description | Time Cost |
|--------|--------|-------------|-----------|
| **Investigate** | `{"action_type": "investigate", "target_service": "..."}` | Service overview, deploys, dependencies | 2 min |
| **Check Logs** | `{"action_type": "check_logs", "target_service": "..."}` | Recent log lines (root cause clues) | 3 min |
| **Check Metrics** | `{"action_type": "check_metrics", "target_service": "..."}` | Live metrics: error_rate, p99, cpu, etc. | 1 min |
| **Restart** | `{"action_type": "restart", "target_service": "..."}` | Restart a service | 5 min |
| **Rollback** | `{"action_type": "rollback", "target_service": "..."}` | Roll back to previous version | 8 min |
| **Scale** | `{"action_type": "scale", "target_service": "..."}` | Scale up replicas | 3 min |
| **Escalate** | `{"action_type": "escalate", "escalation_target": "..."}` | Page a specialist team | 2 min |
| **Communicate** | `{"action_type": "communicate", "message_type": "..."}` | Post stakeholder status update | 1 min |
| **Resolve** | `{"action_type": "resolve"}` | Declare incident resolved (terminal) | 0 min |

## Observation Space

Each step returns an `IncidentObservation` with:

| Field | Type | Description |
|-------|------|-------------|
| `incident_summary` | str | Natural-language incident description |
| `severity` | str | P1, P2, or P3 |
| `sla_remaining_minutes` | int | Time left before SLA breach |
| `active_alerts` | list | Currently firing alerts with severity |
| `services_investigated` | list | Services the agent has examined |
| `findings` | list | Discovered evidence (log analysis, metric anomalies, etc.) |
| `visible_services` | list | Detailed status of investigated services |
| `mitigations_applied` | list | Fixes attempted and their results |
| `message` | str | Full natural-language summary for LLM consumption |

## Service Architecture

```
                    ┌──────────────┐
                    │  api-gateway │
                    └──────┬───────┘
                     ┌─────┼─────┐
                     ▼     ▼     ▼
               ┌──────┐ ┌──────┐ ┌────────┐
               │auth  │ │order │ │search  │ ← + user-service
               └──┬───┘ └──┬───┘ └───┬────┘
                  │    ┌───┼───┐     │
                  ▼    ▼   ▼   ▼     ▼
              ┌─────┐┌──────┐┌─────────┐┌───────┐
              │user- ││pay-  ││inventory││cache- │
              │svc   ││ment  ││-service ││layer  │
              └──┬───┘└──┬───┘└────┬────┘└───────┘
                 │       │        │
                 └───────┴────────┘
                         ▼
                   ┌──────────┐
                   │primary-db│
                   └──────────┘
```

10 services with realistic dependencies, each tracked with: health, error_rate, p99_latency, cpu, memory, qps, replicas, version, and deploy history.

## Scoring

Each task produces a score in **[0.0, 1.0]** from five weighted components:

| Component | Description |
|-----------|-------------|
| **Root Cause Accuracy** | Did you fix the right service(s) with the right action? |
| **Timeliness** | How much SLA slack remained at resolution? |
| **Customer Impact** | How much damage accumulated during the incident? |
| **Investigation Efficiency** | Useful actions vs. wasted investigation steps |
| **Communication** | Did you keep stakeholders informed? |

Weights shift per difficulty level — easy tasks emphasise root cause accuracy and speed; frontier tasks emphasise investigation efficiency (since finding the root cause is the hard part).

### Per-Step Rewards

The environment provides **meaningful signal throughout the trajectory**, not just at episode end:

- **+0.05** — Checking logs of a root cause service
- **+0.04** — Investigating a root cause service
- **+0.03** — Investigating a related service
- **+0.15** — Applying the correct fix
- **+0.03** — Sending a status update
- **−0.05** — Fixing a healthy service
- **−0.03** — Wrong fix type on a root cause

## Setup & Running

### Prerequisites

- Python ≥ 3.10
- Docker (for container builds)
- `openenv-core` package: `pip install openenv-core`

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_BASE_URL` | Yes | LLM API endpoint |
| `MODEL_NAME` | Yes | Model identifier |
| `HF_TOKEN` or `OPENAI_API_KEY` | Yes | API key |

### Run Locally

```bash
# Install dependencies
pip install -e .

# Start the environment server
uvicorn server.app:app --host 0.0.0.0 --port 8000

# In another terminal, run the agent
API_BASE_URL="https://router.huggingface.co/v1" \
MODEL_NAME="Qwen/Qwen2.5-72B-Instruct" \
HF_TOKEN="your-token" \
python inference.py
```

### Docker

```bash
docker build -t incident-response .
docker run -p 8000:8000 incident-response
```

### Validate

```bash
openenv validate .
```

### Baseline (no LLM needed)

```bash
curl -X POST http://localhost:8000/baseline
```

## File Layout

| File | Purpose |
|------|---------|
| `models.py` | Typed Action, Observation, Alert, Finding, ServiceStatus Pydantic models |
| `service_graph.py` | 10-service microservice topology, dependencies, default healthy metrics |
| `scenarios.py` | 4 incident scenarios with pre-written logs, investigation content, failure schedules |
| `tasks.py` | 5-component grading formula with task-specific weights |
| `client.py` | EnvClient subclass for WebSocket communication |
| `inference.py` | LLM agent inference script with hackathon logging format |
| `server/incident_environment.py` | Core simulation engine (step/reset/state) |
| `server/app.py` | FastAPI server with /tasks and /baseline endpoints |
| `Dockerfile` | Container build for HF Spaces |
| `openenv.yaml` | OpenEnv manifest with task definitions |
