---
title: Supply Chain Hub
emoji: 🚚
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
pinned: false
---
# Supply Chain Logistics Router — OpenEnv Environment

A deterministic, seeded logistics-routing environment for evaluating AI agents on operational decision-making under dynamic weather and traffic conditions.

## Overview

The agent controls a single truck navigating a **4×4 grid** (16 nodes) from origin `N0` to destination `N15`. The environment is **partially observable** — the agent sees route summaries, weather/traffic conditions, and time/fuel status. It must decide at each node whether to **move** to an adjacent node or **wait** for conditions to improve.

This models a real-world last-mile logistics problem: dispatching a delivery truck through a city graph with weather disruptions, traffic incidents, and tight deadlines.

### Progressive Difficulty

The environment uses **progressive information reduction** across tasks to test increasing reasoning capability:

| Level | Info Given | Reasoning Required |
|-------|-----------|-------------------|
| Easy | Grid coords + "CLOSER/farther" labels + hop distance | Minimal — follow hints |
| Medium | Grid coords only (no direction hints) | Spatial reasoning from coordinates |
| Hard | Grid coords only + initial storm + tight deadline | Temporal reasoning + efficient waiting |
| Frontier | Grid coords only + mid-route storm trap | Multi-step planning + counter-intuitive decisions |

## Action Space

| Action | Format | Description |
|--------|--------|-------------|
| **Move** | `{"action_type": "move", "target_node": "N5"}` | Move to an adjacent node |
| **Wait 10 min** | `{"action_type": "wait", "wait_minutes": 10}` | Wait at current node for 10 min |
| **Wait 20 min** | `{"action_type": "wait", "wait_minutes": 20}` | Wait at current node for 20 min |

Invalid actions (non-adjacent target, blocked route) return an error message without crashing.

## Observation Space

Each step returns a `RouterObservation`:

| Field | Type | Description |
|-------|------|-------------|
| `truck_location` | str | Current node ID |
| `destination` | str | Target node ID |
| `time_remaining_minutes` | int | Minutes left before deadline |
| `elapsed_minutes` | int | Minutes elapsed since start |
| `fuel_remaining` | float | Fuel gauge (0 = out of fuel) |
| `route_options` | list | Adjacent routes with ETA, weather, risk, trend |
| `available_actions` | list | Valid action strings |
| `last_action_summary` | str | What happened last step |
| `last_action_error` | str | Error if last action was invalid |
| `alerts` | list | Warnings for high-risk/blocked routes |
| `message` | str | Natural-language summary (task-dependent detail level) |

Each **route option** includes: `to_node`, `base_travel_time_minutes`, `traffic_delay_minutes`, `weather`, `risk_level` (Low/Medium/High/Blocked), `edge_status` (open/degraded/blocked), `eta_to_next_node`, `fuel_cost_estimate`, `trend` (improving/stable/worsening).

## Task Families

| # | Task | Difficulty | Description | Key Challenge |
|---|------|-----------|-------------|---------------|
| 1 | `1_easy_clear_path` | Easy | Clear weather, no traffic, generous deadline | Follow "CLOSER" hints to destination |
| 2 | `2_medium_congestion` | Medium | Severe traffic blocks diagonal routes, no direction hints | Must compute direction from (row,col) coords + find detour |
| 3 | `3_hard_strategic_wait` | Hard | Storm blocks NW region at start, tight deadline | Must wait efficiently (not too long), then navigate precisely |
| 4 | `4_frontier_greedy_trap` | Frontier | SE storm hits mid-route, very tight constraints | Must detect "worsening" trend + plan counter-intuitively |

## Scoring

Each task produces a score in **[0.0, 1.0]** from three weighted components:

- **Timeliness** — How much deadline slack remained at arrival
- **Safety** — Penalized for traversing high-risk edges (−0.3 High, −0.1 Medium)
- **Efficiency** — Actual travel time vs. optimal baseline

| Task | Timeliness | Safety | Efficiency |
|------|-----------|--------|------------|
| Easy | 50% | 20% | 30% |
| Medium | 40% | 20% | 40% |
| Hard | 30% | 30% | 40% |
| Frontier | 20% | 50% | 30% |

Score is **0.0** if the truck doesn't arrive before the deadline or runs out of fuel.

## Setup & Running

### Prerequisites

- Python ≥ 3.10
- Docker (for container builds)
- `openenv-core` package: `pip install openenv-core`

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_BASE_URL` | Yes | LLM API endpoint (e.g., `https://router.huggingface.co/v1`) |
| `MODEL_NAME` | Yes | Model identifier (e.g., `Qwen/Qwen2.5-72B-Instruct`) |
| `HF_TOKEN` | Yes | Hugging Face API token |

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
docker build -t logistics-router .
docker run -p 8000:8000 logistics-router
```

### Validate

```bash
openenv validate .
```

## File Layout

| File | Purpose |
|------|---------|
| `models.py` | Typed Action, Observation, RouteOption Pydantic models |
| `graph.py` | 4×4 grid topology, scenario templates, weather/traffic math |
| `tasks.py` | Per-task grading weights |
| `client.py` | EnvClient subclass for WebSocket communication |
| `inference.py` | LLM agent inference script (hackathon `[START]/[STEP]/[END]` format) |
| `server/router_environment.py` | Core simulation engine (step/reset/state) |
| `server/app.py` | FastAPI server entry point |
| `Dockerfile` | Container build for HF Spaces |
| `openenv.yaml` | OpenEnv environment manifest |
