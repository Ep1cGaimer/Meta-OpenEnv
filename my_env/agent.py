import json
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv
from client import LogisticsClient
from models import LogisticsAction

load_dotenv()

client = genai.Client()

def call_llm_policy(observation_text: str) -> LogisticsAction:
    """
    Calls Gemini 1.5 Flash to determine the next logistics action based on the observation.
    """
    system_prompt = """
    You are an autonomous logistics routing agent. 
    Read the observation containing your current location, weather, and traffic data.
    Choose whether to MOVE to an adjacent node or WAIT.
    """

    # Enforce the exact JSON structure required by our OpenEnv LogisticsAction model
    action_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "action_type": types.Schema(type=types.Type.STRING, enum=["MOVE", "WAIT"]),
            "target_node": types.Schema(type=types.Type.STRING, nullable=True),
            "wait_time_mins": types.Schema(type=types.Type.INTEGER, nullable=True),
        },
        required=["action_type"],
    )

    # Call Gemini 1.5 Flash
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=observation_text,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=action_schema,
            temperature=0.1, # Low temperature for more deterministic routing logic
        ),
    )
    
    # Parse the JSON string back into a Python dictionary
    try:
        output = json.loads(response.text)
    except json.JSONDecodeError:
        # Fallback in case of a highly unlikely parsing error
        print("Failed to parse JSON, falling back to WAIT.")
        output = {"action_type": "WAIT", "wait_time_mins": 60}
    
    return LogisticsAction(
        action_type=output["action_type"],
        target_node=output.get("target_node"),
        wait_time_mins=output.get("wait_time_mins")
    )

def run_evaluation_loop(num_episodes=5):
    """
    The main loop connecting the OpenEnv client to your LLM policy.
    """
    # Assuming the OpenEnv server is running locally on port 8000
    with LogisticsClient(base_url="http://localhost:8000").sync() as env:
        
        for episode in range(num_episodes):
            print(f"\n=== Starting Episode {episode + 1} ===")
            
            # 1. Reset the environment and get initial observation
            result = env.reset()
            done = False
            total_reward = 0.0
            step = 0
            
            while not done:
                step += 1
                current_obs = result.observation
                
                print(f"\n--- Step {step} ---")
                print(current_obs.llm_prompt)
                
                # 2. Pass the text observation to Gemini and get a structured Action
                action = call_llm_policy(current_obs.llm_prompt)
                print(f"LLM Action Selected: {action.action_type} -> {action.target_node or action.wait_time_mins}")
                
                # 3. Step the OpenEnv environment with the chosen action
                result = env.step(action)
                
                # 4. Accumulate rewards and check termination
                done = result.done
                total_reward += result.reward
                print(f"Step Reward: {result.reward} | Total Reward: {total_reward}")
                
            print(f"\nEpisode {episode + 1} Finished! Final Reward: {total_reward}")

if __name__ == "__main__":
    run_evaluation_loop(num_episodes=1)