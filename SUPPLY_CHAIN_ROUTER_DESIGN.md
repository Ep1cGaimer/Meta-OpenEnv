# Supply Chain / Logistics Router Design

## 1. Purpose

This project should model a single-truck logistics dispatcher that must move a truck from an origin node to a destination node under changing traffic and weather conditions. The environment is fully simulated and does not depend on live APIs.

The core design goal is not to simulate driving in detail. The goal is to test whether an agent can make good routing decisions under uncertainty:

- take the shortest safe route when conditions are good
- avoid unsafe or closure-prone routes when weather turns bad
- decide when waiting briefly is better than committing to a poor detour

The environment should therefore be designed as a compact, deterministic, partially observable route-planning simulator rather than a road-level physics simulator.

## 2. Design Principles

### 2.1 Focus on decisions, not low-level realism

The environment should present the agent with high-value operational decisions:

- choose among a few adjacent route options
- weigh time efficiency against safety
- exploit short-term forecasts by waiting when conditions are likely to improve

The environment should not ask the agent to micromanage speed, steering, or raw map coordinates. Those details add complexity without improving the reasoning benchmark.

### 2.2 Partially observable by design

The task is most interesting when the agent does not know the full future state of the network. It should only see a local operational view:

- current node
- destination
- remaining time
- route summaries for adjacent edges
- a coarse short-term forecast or trend

This makes the problem a POMDP rather than a trivial shortest-path problem over a fully known graph.

### 2.3 Deterministic and seeded

Because the hackathon requires reproducible tasks and graders, every episode should be generated from a seed. A fixed seed should always produce the same map conditions, event schedule, and scoring outcome.

### 2.4 Small enough for evaluation

The environment and baseline inference must run under modest resource limits. The simulator should therefore use:

- a small graph, typically 6 to 10 nodes
- discrete time updates
- precomputed or cheaply computed route estimates
- no external network dependencies

## 3. Hackathon-Driven Constraints

The requirements image implies several design constraints that should shape the environment:

- OpenEnv spec compliance is mandatory
- the environment must expose typed `reset()`, `step()`, and `state()` behavior
- there must be at least 3 tasks with graders
- reward or grading outputs must stay in the `0.0` to `1.0` range
- the system must be deterministic enough for reproducible scoring
- the total inference and evaluation runtime should remain well below 20 minutes on limited hardware

These constraints strongly favor a compact graph simulator with seeded scenarios over any large stochastic world model.

## 4. Recommended Problem Formulation

The right formulation is:

> A single-truck dispatch environment on a city graph with dynamic weather and traffic, where the agent acts at route decision points and must maximize on-time safe delivery under partial observability.

This can be formalized as a POMDP with:

- hidden state: full graph conditions and future event persistence
- observation: local route summaries and limited forecast information
- action: move to a neighboring node or wait
- reward: normalized delivery quality combining timeliness, safety, and efficiency

## 5. Environment Structure

### 5.1 Graph

Represent the road network as a directed or undirected weighted graph.

Each node is a city, hub, junction, or region checkpoint.

Each edge stores:

- `base_travel_time_minutes`
- `distance_km` or a proxy for route length
- `road_type`: highway, arterial, mountain, coastal, rural
- `weather_sensitivity`: how strongly rain or storms degrade it
- `incident_sensitivity`: how likely it is to receive traffic incidents
- `closure_threshold`: the weather level at which the edge becomes blocked

The graph should be small but intentionally structured. It should include:

- a short path that is often risky
- a longer path that is usually safe
- at least one branch where waiting can become the optimal choice

That structure creates meaningful tradeoffs.

### 5.2 Time Model

Use discrete time with a base unit of 10 minutes.

Important design choice:

- the agent only acts when the truck is at a node
- traversing an edge internally consumes multiple 10-minute ticks
- waiting consumes one or more ticks without changing location

This preserves temporal dynamics while keeping the action space small. It also avoids asking the agent to make meaningless mid-edge decisions.

### 5.3 Truck State

At any moment, the truck is either:

- `at_node`
- `arrived`
- `failed`

To keep the interaction simple, edge traversal should resolve atomically in one step. A move action advances simulation time by the travel cost of that edge and places the truck at the next node.

This is preferable to exposing `on_edge` state unless the project explicitly wants interruption or rerouting while in transit.

## 6. Hidden Environment State

The environment should maintain a richer internal state than what is shown to the LLM.

Recommended hidden state fields:

- `episode_seed`
- `current_node`
- `destination_node`
- `current_time_minutes`
- `deadline_minutes`
- `elapsed_minutes`
- `visited_nodes`
- `path_history`
- `arrived`
- `failed`
- `graph_definition`
- `regional_weather_state`
- `edge_incident_state`
- `event_schedule`
- `latest_score_components`

### 6.1 Weather State

Weather should not be random per edge each step. It should be region-based and persistent.

Recommended weather categories:

- `Clear`
- `LightRain`
- `HeavyRain`
- `Storm`

Each node or region belongs to a weather region. Weather state evolves with persistence, either by:

- a simple seeded schedule of intervals, or
- a duration-based Markov process with deterministic sampling from the episode seed

The schedule approach is better for grading because it is easier to reason about and debug.

### 6.2 Traffic State

Traffic on an edge should depend on:

- baseline congestion for that route
- explicit incidents such as accident or roadwork
- weather spillover from relevant regions

Recommended traffic categories:

- `None`
- `Moderate`
- `Heavy`
- `Severe`

Traffic should also persist over time rather than being redrawn independently at every step.

### 6.3 Forecast State

The environment should internally know the near-term trend for local conditions, but only expose a coarse summary to the agent, such as:

- "likely to worsen"
- "stable"
- "likely to improve within 20 min"

This is what makes the `wait` action rational rather than blind.

## 7. Observation Design

Observation design is the most important part of the environment because it determines what kind of reasoning the agent can perform.

The observation should be structured, concise, and local.

### 7.1 Observation Goals

The agent should be able to answer:

- what options do I have right now
- which option is fastest
- which option is safest
- will conditions likely improve if I wait
- how much time do I have left

The agent should not need to infer this from raw simulator internals.

### 7.2 Recommended Observation Fields

- `truck_location`
- `destination`
- `time_remaining_minutes`
- `elapsed_minutes`
- `available_actions`
- `route_options`
- `last_action_summary`
- `alerts`
- `done`
- `reward`

Each `route_option` should include:

- `to_node`
- `base_travel_time_minutes`
- `traffic_delay_minutes`
- `weather`
- `risk_level`
- `edge_status`: open, degraded, blocked
- `eta_to_next_node`
- `estimated_total_eta_to_destination`
- `trend`: improving, stable, worsening

### 7.3 LLM-Friendly Observation Rendering

The structured observation should also support a natural-language rendering for inference scripts.

Example:

```text
Truck at C. Destination F. Time remaining: 120 min.

Route options:
1. C -> D | ETA 75 min total to next node and destination segment | traffic Heavy (+45 min) | weather Clear | risk Low | trend Stable
2. C -> E | ETA 60 min total to next node and destination segment | traffic Light (+5 min) | weather HeavyRain | risk High | trend Improving within 20 min

Additional action:
3. Wait 10 min | expected effect: rain near E may drop from HeavyRain to LightRain

Last action result: Arrived at C after 30 min travel.
```

This is significantly better than showing raw JSON or all graph details.

## 8. Action Space

The action space should stay intentionally small.

Recommended actions:

- `move_to(node_id)` where `node_id` is one of the current node's neighbors
- `wait(minutes)` where `minutes` is one of a small allowed set such as `10` or `20`

### 8.1 Why not include reroute as a separate primitive

"Reroute" is not meaningfully different from choosing a different adjacent node. It should not be a separate primitive action.

If the current node offers paths to `D` and `E`, choosing `E` is already rerouting.

### 8.2 Why not include continuous actions

Continuous actions such as custom waiting durations or route weights create unnecessary ambiguity and make grading harder. A discrete action space is easier for both LLMs and evaluation.

## 9. Transition Dynamics

### 9.1 Move Action

When the agent chooses `move_to(X)`:

1. validate that `X` is adjacent and the edge is not blocked
2. compute travel time from:
   - base edge cost
   - traffic delay
   - weather penalty
3. advance simulation time by that total
4. apply any scheduled environmental updates that would occur during the elapsed time
5. place the truck at node `X`
6. update path history and loop counters

### 9.2 Wait Action

When the agent chooses `wait(10)` or `wait(20)`:

1. keep the truck at the same node
2. advance simulation time by the wait duration
3. update weather and traffic according to the event schedule
4. return a refreshed local view

The wait action is only valuable if some conditions actually improve or clear on realistic timescales. That should be guaranteed in at least one major task family.

### 9.3 Invalid Actions

Invalid actions should not crash the environment. They should produce:

- a valid observation
- a low normalized reward
- an alert explaining the issue

Example invalid actions:

- moving to a non-adjacent node
- moving across a blocked edge
- waiting with an unsupported duration

## 10. Why This Should Be a POMDP

If the agent can see the entire graph and the full future condition schedule, the environment collapses into a deterministic planning problem and stops being interesting.

Partial observability is important because it creates realistic uncertainty:

- the agent sees local route conditions, not global certainty
- the agent gets trend hints, not perfect forecasts
- route quality may depend on conditions a short time into the future

That uncertainty is what makes `wait` a meaningful action and what differentiates this task from plain shortest-path search.

## 11. Reward and Scoring Design

The project requirements suggest that visible reward or grader outputs should lie in the `0.0` to `1.0` range. The cleanest design is:

- expose a normalized reward in each observation
- compute a final episode score in `[0, 1]`
- use that same final score inside task-specific graders

### 11.1 Desired Behavior

The scoring function should reward:

- reaching the destination
- arriving before the deadline
- avoiding dangerous or blocked routes
- not taking wasteful loops or detours

The scoring function should penalize:

- timing out
- traversing severe-weather edges
- taking obviously poor routes when safer and faster options were available
- cycling between nodes

### 11.2 Recommended Final Score

If the truck does not arrive, final score should be `0.0`.

If the truck arrives, compute:

- `timeliness_score`
- `safety_score`
- `efficiency_score`

Suggested formula:

```text
final_score =
    0.50 * timeliness_score +
    0.30 * safety_score +
    0.20 * efficiency_score
```

Where:

- `timeliness_score` measures how much deadline slack remained at arrival
- `safety_score` drops when the truck traverses high-risk or severe-weather edges
- `efficiency_score` compares actual travel time to a safe baseline for that scenario

All three components should be clipped to `[0, 1]`.

### 11.3 Step Reward

Per-step reward should also remain normalized and simple. Recommended approach:

- before episode end, emit a small progress-oriented score in `[0, 1]`
- on the final step, emit the final episode score

This makes the environment compliant with the visible reward requirement without needing negative rewards.

## 12. Task Suite Design

The environment needs at least 3 tasks with graders. The best task design is not 3 arbitrary maps, but 3 scenario families that each test a distinct capability.

### Task 1: Congestion Avoidance

Purpose:

- test whether the agent can avoid heavy traffic and choose efficient detours

Characteristics:

- weather is mostly benign
- one short route becomes heavily delayed
- a slightly longer alternative remains efficient

Expected good behavior:

- select the best detour rather than blindly following the shortest nominal path

Grader emphasis:

- timeliness and efficiency

### Task 2: Severe Weather Detour

Purpose:

- test whether the agent prioritizes safety when the shortest path becomes dangerous

Characteristics:

- one corridor is fast but weather-sensitive
- storm or heavy rain pushes the risk above a safe threshold
- a safer but slower path exists

Expected good behavior:

- avoid high-risk or blocked edges even if the nominal ETA is lower

Grader emphasis:

- safety first, then timeliness

### Task 3: Strategic Waiting

Purpose:

- test whether the agent can exploit forecast trends rather than committing too early

Characteristics:

- one desirable route is temporarily degraded
- conditions improve within a short predictable horizon
- a detour exists but is materially slower

Expected good behavior:

- wait briefly when the expected improvement outweighs the delay

Grader emphasis:

- balanced evaluation of timing, safety, and decision quality

### Optional Task 4: Mixed Conditions

Purpose:

- combine traffic, weather, and deadline pressure into a more realistic benchmark

This task is useful for a final demo but is not strictly required if three task families are already implemented well.

## 13. Scenario Generation

### 13.1 Base Scenario Templates

Each task family should define a small library of templates. A template specifies:

- graph topology
- start and destination
- deadline
- base edge attributes
- weather schedule by region
- traffic incident schedule by edge

### 13.2 Seeded Variation

A seed can vary:

- incident start time
- incident duration
- which branch receives weather pressure
- deadline tightness
- forecast trend wording

This creates replayable variation while preserving deterministic grading.

### 13.3 Difficulty Scaling

Difficulty can be controlled through:

- tighter deadlines
- more ambiguous route tradeoffs
- less forgiving wait windows
- more overlap between traffic and weather penalties

## 14. Baselines and Evaluation Philosophy

The grader should not assume the LLM will discover a mathematically perfect policy. It should instead assess whether the chosen behavior is operationally reasonable for the scenario.

Recommended baselines:

- shortest nominal path baseline
- shortest safe path baseline under realized conditions
- simple rule-based dispatcher baseline

A good environment should clearly outperform the nominal shortest-path baseline when dynamic conditions matter.

## 15. OpenEnv Mapping

The current repo already has the OpenEnv scaffold. The logistics design maps naturally onto it.

### 15.1 Action Model

`RouterAction` should become a typed routing action.

Recommended fields:

- `action_type`: `move` or `wait`
- `target_node`: optional, required when `action_type == "move"`
- `wait_minutes`: optional, required when `action_type == "wait"`

### 15.2 Observation Model

`RouterObservation` should describe the current decision state.

Recommended fields:

- `truck_location`
- `destination`
- `time_remaining_minutes`
- `route_options`
- `alerts`
- `last_action_summary`
- `done`
- `reward`
- `metadata`

Where `route_options` is a typed list of compact route descriptions rather than free-form text.

### 15.3 Environment State

`server/router_environment.py` should hold:

- the seeded scenario generator
- the graph definition
- the weather and traffic update logic
- transition and scoring logic

The `state()` endpoint should expose enough internal information for debugging and grading, but the default step observation should remain intentionally partial.

## 16. Recommended Internal Data Shapes

The exact classes can vary, but these logical structures are useful:

### 16.1 Edge Definition

```python
{
    "from_node": "C",
    "to_node": "D",
    "base_travel_time": 30,
    "road_type": "highway",
    "weather_sensitivity": 0.4,
    "incident_sensitivity": 0.7,
    "closure_threshold": "Storm",
}
```

### 16.2 Route Option in Observation

```python
{
    "to_node": "D",
    "eta_to_next_node": 75,
    "estimated_total_eta_to_destination": 95,
    "traffic_delay_minutes": 45,
    "weather": "Clear",
    "risk_level": "Low",
    "edge_status": "open",
    "trend": "stable",
}
```

### 16.3 Episode Score Breakdown

```python
{
    "timeliness_score": 0.82,
    "safety_score": 1.00,
    "efficiency_score": 0.76,
    "final_score": 0.86,
}
```

## 17. Failure Conditions and Episode Termination

An episode should end when:

- the truck reaches the destination
- the deadline is exceeded
- the maximum allowed number of decisions is reached
- the scenario becomes impossible and the environment declares failure

Termination should always return a valid observation with:

- `done = True`
- `reward` in `[0, 1]`
- clear final metadata

## 18. What Makes This Environment Good

This design is good if the following statements are true:

- the best action is not always the nominal shortest path
- `wait` is sometimes optimal and not merely decorative
- route safety matters enough to change decisions
- episodes are reproducible under a seed
- observations are simple enough for an LLM to reason over in a few steps
- graders are explainable and normalized

If those properties hold, the environment will feel intentional rather than arbitrary.

## 19. Recommended Implementation Order

1. Replace the echo environment with typed routing actions and observations.
2. Implement a fixed graph and one seeded scenario template.
3. Add dynamic weather and traffic schedules with persistence.
4. Implement scoring and normalized reward.
5. Add three scenario families and corresponding graders.
6. Add a simple deterministic baseline policy.
7. Add the inference script and required structured logging.

This order reduces risk and keeps the environment testable at each stage.

## 20. Final Recommendation

The best version of this project is not "Google Maps and weather APIs, but mocked." The best version is a deliberately designed operational decision benchmark:

- small graph
- seeded episodes
- persistent weather and traffic
- local observations
- discrete route and wait actions
- normalized, explainable scoring

That gives you a clean hackathon story, a tractable implementation, and a benchmark where the LLM is actually being tested on reasoning rather than just reacting to surface-level text.
