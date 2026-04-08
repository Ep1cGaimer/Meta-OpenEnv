"""
Inference script for the Supply Chain Logistics Router.

Runs the LLM agent through all 3 task scenarios, logging in the exact
[START]/[STEP]/[END] format required by the hackathon evaluator.

Env vars:
    API_BASE_URL   LLM endpoint (default: Ollama local)
    MODEL_NAME     Model ID (default: gemma4:e4b)
    HF_TOKEN       API key (optional for Ollama)
    IMAGE_NAME     Docker image name (if using from_docker_image)
"""

import asyncio
import json
import os
import re
import textwrap
from typing import List, Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

from client import RouterEnv
from models import RouterAction

IMAGE_NAME = os.getenv("IMAGE_NAME")
API_KEY = os.getenv("HF_TOKEN") or os.getenv("API_KEY") or "ollama"
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:11434/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gemma-aggressive")
BENCHMARK = "logistics_router"
MAX_STEPS = 20
TEMPERATURE = 0.3
MAX_TOKENS = 100

ALL_TASK_NAMES = ["1_easy_clear_path", "2_medium_congestion", "3_hard_strategic_wait", "4_frontier_greedy_trap", "5_impossible_dynamic_maze"]

SYSTEM_PROMPT = textwrap.dedent("""
You are a logistics route dispatcher. Each turn you receive a situation report
about your truck's position, weather, and traffic conditions. You must choose
one action to take.

Respond with ONLY a valid JSON object. No explanation, no markdown, no extra text.

Valid actions:
  {"action_type": "move", "target_node": "<NODE_ID>"}
  {"action_type": "wait", "wait_minutes": 10}
  {"action_type": "wait", "wait_minutes": 20}

Strategy guidelines:
- Reach the destination before time runs out.
- Avoid routes marked High risk or BLOCKED.
- If a good route shows trend "improving", consider waiting.
- Prefer open, low-risk routes even if slightly longer.
- DO NOT revisit nodes you have already visited (check your path history) unless absolutely necessary.
""").strip()


# ---------------------------------------------------------------------------
# Logging — exact hackathon format
# ---------------------------------------------------------------------------

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)

def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}", flush=True)

def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}", flush=True)


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

import time

REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0"))


def parse_llm_response(text: str) -> RouterAction:
    """
    Parse the LLM's JSON response into a RouterAction.
    Falls back to wait(10) if parsing fails.
    """
    clean = text.strip()

    # Strip markdown fences (```json ... ```) that Gemini/Llama often wrap around JSON
    if clean.startswith("```"):
        lines = clean.splitlines()
        if len(lines) >= 2:
            clean = "\n".join(lines[1:-1]).strip()

    # Try direct JSON parse
    try:
        data = json.loads(clean)
        return RouterAction(**data)
    except (json.JSONDecodeError, Exception):
        pass

    # Try extracting first JSON object from surrounding text
    match = re.search(r'\{[^}]+\}', text)
    if match:
        try:
            data = json.loads(match.group())
            return RouterAction(**data)
        except (json.JSONDecodeError, Exception):
            pass

    # Safe fallback — don't crash the inference
    return RouterAction(action_type="wait", wait_minutes=10)


def get_llm_action(client: OpenAI, observation_message: str) -> RouterAction:
    """Send the observation to the LLM and parse its response into an action."""
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": observation_message},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
        text = (completion.choices[0].message.content or "").strip()
        return parse_llm_response(text)
    except Exception as exc:
        print(f"[DEBUG] LLM request failed: {exc}", flush=True)
        return RouterAction(action_type="wait", wait_minutes=10)


def action_to_str(action: RouterAction) -> str:
    """Format action for the [STEP] log line."""
    if action.action_type == "move":
        return f"move_to({action.target_node})"
    return f"wait({action.wait_minutes})"


# ---------------------------------------------------------------------------
# Main inference loop
# ---------------------------------------------------------------------------

async def run_task(llm_client: OpenAI, env: RouterEnv, task_name: str) -> None:
    """Run one task scenario through the LLM agent."""
    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    log_start(task=task_name, env=BENCHMARK, model=MODEL_NAME)

    try:
        result = await env.reset(task_name=task_name)

        for step in range(1, MAX_STEPS + 1):
            if result.done:
                break

            action = get_llm_action(llm_client, result.observation.message)
            result = await env.step(action)

            reward = result.reward or 0.0
            done = result.done
            error = result.observation.last_action_error or None
            rewards.append(reward)
            steps_taken = step

            log_step(step=step, action=action_to_str(action), reward=reward, done=done, error=error)

            if done:
                break

            # Configurable delay to stay under API rate limits (e.g. REQUEST_DELAY=4 for Gemini free tier)
            if REQUEST_DELAY > 0:
                time.sleep(REQUEST_DELAY)

        # Final score is the reward from the last step (which is the episode final score on arrival)
        score = rewards[-1] if rewards else 0.0
        score = max(0.0, min(1.0, score))
        success = score > 0.1

    except Exception as exc:
        print(f"[DEBUG] Task {task_name} failed: {exc}", flush=True)

    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)


async def main() -> None:
    llm_client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    # Connect to environment — via Docker image or local server
    if IMAGE_NAME:
        env = await RouterEnv.from_docker_image(IMAGE_NAME)
    else:
        base_url = os.getenv("ENV_BASE_URL", "http://localhost:8000")
        env = RouterEnv(base_url=base_url)

    try:
        for task_name in ALL_TASK_NAMES:
            await run_task(llm_client, env, task_name)
    finally:
        try:
            await env.close()
        except Exception as e:
            print(f"[DEBUG] env.close() error: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
