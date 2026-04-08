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

The agent controls a single truck navigating a **4×4 grid** (16 nodes) from origin `N0` to destination `N15`. The environment is **partially observable** — the agent sees only local route summaries, short-term trend forecasts, and time/fuel remaining. It must decide at each node whether to **move** to an adjacent node or **wait** for conditions to improve.

This models a real-world last-mile logistics problem: dispatching a delivery truck through a city graph with weather disruptions, traffic incidents, and tight deadlines.

## Action Space

The agent sends a JSON action each turn:

| Action | Format | Description |
|--------|--------|-------------|
| **Move** | `{"action_type": "move", "target_node": "N5"}` | Move to an adjacent node |
| **Wait 10 min** | `{"action_type": "wait", "wait_minutes": 10}` | Wait at current node for 10 min |
| **Wait 20 min** | `{"action_type": "wait", "wait_minutes": 20}` | Wait at current node for 20 min |

Invalid actions (non-adjacent target, blocked route) return an error message without crashing the episode.

## Observation Space

Each step returns a structured `RouterObservation` containing:

| Field | Type | Description |
|-------|------|-------------|
| `truck_location` | str | Current node ID |
| `destination` | str | Target node ID |
| `time_remaining_minutes` | int | Minutes left before deadline |
| `elapsed_minutes` | int | Minutes elapsed since episode start |
| `fuel_remaining` | float | Fuel gauge (0 = out of fuel, episode ends) |
| `route_options` | list | Adjacent routes with ETA, weather, risk, trend |
| `available_actions` | list | Valid action strings |
| `last_action_summary` | str | What happened on the previous step |
| `last_action_error` | str | Error message if last action was invalid |
| `alerts` | list | High-risk or blocked route warnings |
| `message` | str | Natural-language summary (fed to LLM) |

Each **route option** includes: `to_node`, `base_travel_time_minutes`, `traffic_delay_minutes`, `weather`, `risk_level` (Low/Medium/High/Blocked), `edge_status` (open/degraded/blocked), `eta_to_next_node`, `fuel_cost_estimate`, `trend` (improving/stable/worsening).

## Task Families

| Task | Difficulty | Description |
|------|-----------|-------------|
| `1_easy_clear_path` | Easy | Clear weather, no traffic. Test basic shortest-path reasoning. |
| `2_medium_congestion` | Medium | Severe traffic on the central corridor. Agent must find a detour. |
| `3_hard_strategic_wait` | Hard | Storm blocks NW region at start, clears mid-episode. Wait or detour? |
| `4_frontier_greedy_trap` | Frontier | Storm hits SE (near destination) mid-route, trapping greedy agents. |

## Scoring

Each task produces a score in **[0.0, 1.0]** computed from three components:

- **Timeliness**: How much deadline slack remained at arrival
- **Safety**: Penalized for traversing high-risk edges (−0.3 for High, −0.1 for Medium)
- **Efficiency**: Actual travel time vs. optimal baseline

Weights vary per task (e.g., the frontier task weights safety at 50%). Score is 0.0 if the truck doesn't arrive.

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

# In another terminal, run the inference script
API_BASE_URL="https://router.huggingface.co/v1" \
MODEL_NAME="Qwen/Qwen2.5-72B-Instruct" \
HF_TOKEN="your-token" \
python inference.py
```

### Docker Build

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
| `models.py` | Typed Action, Observation, RouteOption models |
| `graph.py` | 4×4 grid topology, weather/traffic math, scenario templates |
| `tasks.py` | Per-task grading weights |
| `client.py` | EnvClient subclass for WebSocket communication |
| `inference.py` | LLM inference script (hackathon format) |
| `server/router_environment.py` | Core simulation engine |
| `server/app.py` | FastAPI server entry point |
| `Dockerfile` | Container build for HF Spaces |
| `openenv.yaml` | OpenEnv environment manifest |
