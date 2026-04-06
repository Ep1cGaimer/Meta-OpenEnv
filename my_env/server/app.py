# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
FastAPI application for the Logistics Router Environment.

This module creates an HTTP server that exposes the LogisticsEnvironment
over HTTP and WebSocket endpoints, compatible with EnvClient.

Endpoints:
    - POST /reset: Reset the environment
    - POST /step: Execute an action
    - GET /state: Get current environment state
    - GET /schema: Get action/observation schemas
    - WS /ws: WebSocket endpoint for persistent sessions
"""

import sys
import os

# Add the parent directory to Python's path to permanently fix the relative import error
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from openenv.core.env_server.http_server import create_app
except Exception as e:  # pragma: no cover
    raise ImportError(
        "openenv is required for the web interface. Install dependencies with '\n    uv sync\n'"
    ) from e

# Import the Logistics models and environment
# (Assuming models.py is in the root directory and env.py is in the server directory)
try:
    from models import LogisticsAction, LogisticsObservation
    from server.my_env_environment import LogisticsEnvironment
except ModuleNotFoundError:
    # Fallback if running directly from within the server directory
    from models import LogisticsAction, LogisticsObservation
    from server.my_env_environment import LogisticsEnvironment


# Create the app with web interface and README integration
app = create_app(
    LogisticsEnvironment,
    LogisticsAction,
    LogisticsObservation,
    env_name="logistics_env",
    max_concurrent_envs=100,  # Increased to allow for multiple LLM agents/loops
)


def main(host: str = "0.0.0.0", port: int = 8000):
    """
    Entry point for direct execution via uv run or python -m.

    This function enables running the server without Docker:
        uv run --project . server
        uv run --project . server --port 8001
        python -m server.app
    """
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    main(port=args.port)