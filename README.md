---
title: Supply Chain Hub
emoji: 🚚
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
pinned: false
---
# Meta-OpenEnv: Supply Chain Router

A deterministic, seeded logistics-routing benchmark for testing route decisions under traffic and weather uncertainty.

## Overview

The agent controls one truck moving through a small graph from an origin to a destination.  
The environment is partially observable and exposes only local route summaries, a short forecast, and the time remaining.

## Key mechanics

- Discrete `move` and `wait` actions
- Dynamic weather and traffic with seeded persistence
- Normalized rewards and final scores in `[0.0, 1.0]`
- No live APIs or external dependencies
- Typed `reset()`, `step()`, and `state()` methods

## Task families

1. Congestion avoidance
2. Severe weather detour
3. Strategic waiting

## Implementation reference

See `SUPPLY_CHAIN_ROUTER_DESIGN.md` for the full specification.

## File layout

- `models.py` — Action, Observation, and RouteOption types
- `graph.py` — Graph topology, weather/traffic math, scenario templates
- `tasks.py` — Per-task grading weights
- `client.py` — EnvClient subclass for WebSocket communication
- `inference.py` — LLM inference script (mandatory hackathon format)
- `server/router_environment.py` — Core simulation engine
- `server/app.py` — FastAPI server
- `server/Dockerfile` — Container build
