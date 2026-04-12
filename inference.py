"""
Inference script for the Incident Response Environment.

Runs the LLM agent through all 4 incident scenarios, logging in the
[START]/[STEP]/[END] format required by the hackathon evaluator.

Env vars (set by evaluator):
    API_BASE_URL       LLM endpoint (default: HF router)
    MODEL_NAME         Model ID
    HF_TOKEN           API key (also accepts OPENAI_API_KEY / API_KEY)
    LOCAL_IMAGE_NAME   Docker image name (if using from_docker_image)
    ENV_BASE_URL       Environment server URL (default: http://localhost:8000)
"""

import asyncio
import json
import os
import re
import textwrap
import time
from typing import List, Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

from client import IncidentEnv
from models import IncidentAction

LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME")
API_KEY = (
    os.getenv("HF_TOKEN")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("API_KEY")
)
API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
BENCHMARK = "incident_response"
MAX_STEPS = 15
TEMPERATURE = 0.2
MAX_TOKENS = 200

ALL_TASK_NAMES = [
    "1_easy_payment_deploy",
    "2_medium_db_conn_leak",
    "3_hard_dual_failure",
    "4_frontier_cache_corruption",
]

SYSTEM_PROMPT = textwrap.dedent("""
You are an on-call SRE (Site Reliability Engineer) responding to a production
incident. Your goal is to investigate the root cause, apply the correct fix,
communicate with stakeholders, and resolve the incident before the SLA deadline.

Respond with ONLY a valid JSON object. No explanation, no markdown, no extra text.

Available actions:
  Investigation (costs investigation budget time):
    {"action_type": "investigate", "target_service": "<service_name>"}
    {"action_type": "check_logs", "target_service": "<service_name>"}
    {"action_type": "check_metrics", "target_service": "<service_name>"}

  Remediation (applies a fix):
    {"action_type": "restart", "target_service": "<service_name>"}
    {"action_type": "rollback", "target_service": "<service_name>"}
    {"action_type": "scale", "target_service": "<service_name>"}

  Communication:
    {"action_type": "escalate", "escalation_target": "<team_name>"}
    {"action_type": "communicate", "message_type": "investigating"}

  Terminal (ends the episode):
    {"action_type": "resolve"}

Strategy:
- Start by investigating services mentioned in CRITICAL alerts
- Always check LOGS — they contain root cause clues that metrics alone miss
- Fix the ROOT CAUSE, not symptoms (a service with bad metrics may be a victim,
  not the source of the problem)
- There may be MULTIPLE independent root causes requiring separate fixes
- "rollback" fixes bad deploys, "restart" fixes runtime corruption, "scale"
  fixes capacity issues — choose the right one
- Send at least one "communicate" action to keep stakeholders informed
- A service that looks healthy on metrics may still be the root cause — check
  its logs and look for subtle issues like stale data or replication lag
- After fixing root cause(s), call "resolve" to end the incident
""").strip()


# ---------------------------------------------------------------------------
# Logging — hackathon format
# ---------------------------------------------------------------------------

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)

def log_step(step: int, action: str, reward: float, done: bool,
             error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} "
        f"done={done_val} error={error_val}",
        flush=True,
    )

def log_end(success: bool, steps: int, score: float,
            rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} "
        f"score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0"))

VALID_ACTIONS = {
    "investigate", "check_logs", "check_metrics",
    "restart", "scale", "rollback",
    "escalate", "communicate", "resolve",
}

VALID_MESSAGE_TYPES = {"investigating", "update", "mitigated", "resolved"}
VALID_TEAMS = {
    "platform-team", "accounts-team", "commerce-team",
    "discovery-team", "database-team", "security-team",
}


def parse_llm_response(text: str) -> IncidentAction:
    """Parse LLM JSON into an IncidentAction, with fallback."""
    clean = text.strip()

    # Strip markdown fences
    if clean.startswith("```"):
        lines = clean.splitlines()
        if len(lines) >= 2:
            clean = "\n".join(lines[1:-1]).strip()

    # Try direct parse
    try:
        data = json.loads(clean)
        if data.get("action_type") in VALID_ACTIONS:
            return _sanitize_action(data)
    except (json.JSONDecodeError, Exception):
        pass

    # Try extracting first JSON object
    match = re.search(r'\{[^}]+\}', text)
    if match:
        try:
            data = json.loads(match.group())
            if data.get("action_type") in VALID_ACTIONS:
                return _sanitize_action(data)
        except (json.JSONDecodeError, Exception):
            pass

    # Fallback — safe no-op
    return IncidentAction(action_type="communicate", message_type="update")


def _sanitize_action(data: dict) -> IncidentAction:
    """Ensure only valid fields are passed to IncidentAction."""
    atype = data.get("action_type", "communicate")
    result = {"action_type": atype}

    if "target_service" in data:
        result["target_service"] = str(data["target_service"])
    if "message_type" in data:
        mt = str(data["message_type"])
        result["message_type"] = mt if mt in VALID_MESSAGE_TYPES else "update"
    if "escalation_target" in data:
        result["escalation_target"] = str(data["escalation_target"])

    return IncidentAction(**result)


def get_llm_action(client: OpenAI, observation_message: str,
                    history: List[str]) -> IncidentAction:
    """Send observation to LLM and parse its response."""
    history_text = "\n".join(history[-10:]) if history else "(none)"
    user_prompt = (
        f"{observation_message}\n\n"
        f"Actions taken so far — DO NOT repeat wastefully:\n{history_text}\n\n"
        f"Output next action as JSON."
    )

    try:
        for attempt in range(3):
            try:
                completion = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    stream=False,
                )
                text = (completion.choices[0].message.content or "").strip()
                return parse_llm_response(text)
            except Exception as exc:
                msg = str(exc)
                if "429" in msg or "rate" in msg.lower():
                    time.sleep(10 * (attempt + 1))
                else:
                    raise
    except Exception as exc:
        print(f"[DEBUG] LLM request failed: {exc}", flush=True)

    return IncidentAction(action_type="communicate", message_type="update")


def action_to_str(action: IncidentAction) -> str:
    """Format action for the [STEP] log line."""
    atype = action.action_type
    if atype in ("investigate", "check_logs", "check_metrics",
                 "restart", "rollback", "scale"):
        return f"{atype}({action.target_service})"
    if atype == "escalate":
        return f"escalate({action.escalation_target})"
    if atype == "communicate":
        return f"communicate({action.message_type})"
    return atype


# ---------------------------------------------------------------------------
# Main inference loop
# ---------------------------------------------------------------------------

async def run_task(llm_client: OpenAI, env: IncidentEnv,
                   task_name: str) -> None:
    """Run one incident scenario through the LLM agent."""
    rewards: List[float] = []
    steps_taken = 0
    score = 0.01
    success = False
    history: List[str] = []

    log_start(task=task_name, env=BENCHMARK, model=MODEL_NAME)

    try:
        result = await env.reset(task_name=task_name)

        for step in range(1, MAX_STEPS + 1):
            if result.done:
                break

            action = get_llm_action(
                llm_client, result.observation.message, history
            )

            # Force resolve on last step
            if step == MAX_STEPS and action.action_type != "resolve":
                action = IncidentAction(action_type="resolve")

            result = await env.step(action)

            reward = result.reward or 0.0
            done = result.done
            error = result.observation.last_action_error or None
            rewards.append(reward)
            steps_taken = step

            log_step(
                step=step,
                action=action_to_str(action),
                reward=reward,
                done=done,
                error=error,
            )

            history.append(
                f"Step {step}: {action_to_str(action)} → reward {reward:+.2f}"
            )

            if done:
                break

            if REQUEST_DELAY > 0:
                time.sleep(REQUEST_DELAY)

        score = rewards[-1] if rewards else 0.01
        score = max(0.01, min(0.99, score))
        success = score > 0.1

    except Exception as exc:
        print(f"[DEBUG] Task {task_name} failed: {exc}", flush=True)

    finally:
        log_end(success=success, steps=steps_taken, score=score,
                rewards=rewards)


async def main() -> None:
    llm_client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    if LOCAL_IMAGE_NAME:
        env = await IncidentEnv.from_docker_image(LOCAL_IMAGE_NAME)
    else:
        base_url = os.getenv("ENV_BASE_URL", "http://localhost:8000")
        env = IncidentEnv(base_url=base_url)

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