"""
Scenario definitions for the Incident Response Environment.

Each scenario provides the complete context for one incident episode:
initial service states, root causes with correct fixes, pre-written log and
investigation content, alert definitions, and a failure schedule that drives
cascading degradation over time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Scenario data structures
# ---------------------------------------------------------------------------

@dataclass
class RootCause:
    service: str
    fix: str              # "restart", "rollback", "scale"
    explanation: str

@dataclass
class DegradationEvent:
    """A scheduled state change applied at a specific elapsed‑time tick."""
    tick: int
    service: str
    health: str
    error_rate: float | None = None
    p99_latency_ms: int | None = None
    cpu_percent: float | None = None
    caused_by: str = ""         # root cause service that triggered this

@dataclass
class ScenarioTemplate:
    name: str
    description: str
    difficulty: str             # easy, medium, hard, frontier
    severity: str               # P1, P2, P3
    sla_minutes: int
    investigation_budget: float
    incident_summary: str

    # Initial state overrides (only for non-default services)
    initial_overrides: dict[str, dict] = field(default_factory=dict)

    root_causes: list[RootCause] = field(default_factory=list)

    # {severity, service, message}
    alerts: list[dict] = field(default_factory=list)

    # service → log text
    log_content: dict[str, str] = field(default_factory=dict)

    # service → investigation text
    investigate_content: dict[str, str] = field(default_factory=dict)

    # Scheduled cascading degradation
    degradation_schedule: list[DegradationEvent] = field(default_factory=list)

    # Evidence the grader checks for (pairs: "action:service")
    required_evidence: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 1 — EASY: Payment Service Bad Deploy
# ═══════════════════════════════════════════════════════════════════════════

EASY_PAYMENT_DEPLOY = ScenarioTemplate(
    name="1_easy_payment_deploy",
    description="Payment service failing after a bad deploy — elevated error rates, order processing impacted.",
    difficulty="easy",
    severity="P2",
    sla_minutes=60,
    investigation_budget=100.0,
    incident_summary=(
        "PagerDuty alert: payment-service error rate spiked to 45% approximately "
        "12 minutes ago. order-service is experiencing elevated latency and failures "
        "on payment-related endpoints. Customer-facing checkouts are partially impaired."
    ),
    initial_overrides={
        "payment-service": {
            "health": "failing", "error_rate": 0.45, "p99_latency_ms": 2800,
            "cpu_percent": 35.0, "memory_percent": 60.0, "qps": 1800,
            "replicas": 3, "last_deploy": "12 minutes ago", "version": "v2.4.1",
        },
        "order-service": {
            "health": "degraded", "error_rate": 0.15, "p99_latency_ms": 1200,
            "cpu_percent": 55.0, "memory_percent": 52.0, "qps": 3200,
            "replicas": 3, "last_deploy": "5 days ago", "version": "v4.1.7",
        },
        "api-gateway": {
            "health": "degraded", "error_rate": 0.08, "p99_latency_ms": 380,
            "cpu_percent": 48.0, "memory_percent": 44.0, "qps": 8500,
            "replicas": 6, "last_deploy": "7 days ago", "version": "v5.2.0",
        },
    },
    root_causes=[
        RootCause("payment-service", "rollback",
                  "Version v2.4.1 introduced an incompatible Stripe API version"),
    ],
    alerts=[
        {"severity": "CRITICAL", "service": "payment-service",
         "message": "Error rate 45% — threshold 5%"},
        {"severity": "WARNING", "service": "order-service",
         "message": "p99 latency 1200ms — threshold 500ms"},
        {"severity": "WARNING", "service": "api-gateway",
         "message": "Error rate 8% — threshold 2%"},
    ],
    log_content={
        "payment-service": (
            "14:32:01 ERROR PaymentProcessor: Stripe API version mismatch — "
            "expected 2024-11-01, got 2025-01-15\n"
            "14:32:01 ERROR PaymentProcessor: Failed to deserialize webhook "
            "payload: unknown field 'payment_method_configuration'\n"
            "14:32:02 WARN  HealthCheck: 23 of 50 health probes failed in last 60s\n"
            "14:32:03 ERROR PaymentProcessor: Circuit breaker OPEN for stripe-client "
            "after 25 consecutive failures\n"
            "14:32:04 INFO  DeployTracker: Current version v2.4.1 deployed 12 minutes "
            "ago (previous: v2.3.8)"
        ),
        "order-service": (
            "14:32:10 WARN  OrderProcessor: payment-service returned HTTP 500 for "
            "order #88231\n"
            "14:32:11 WARN  OrderProcessor: Retry 2/3 for payment on order #88232 — "
            "upstream timeout after 5000ms\n"
            "14:32:12 ERROR OrderProcessor: Order #88229 failed permanently: payment "
            "processing unavailable after 3 retries\n"
            "14:32:13 INFO  OrderProcessor: Queuing 15 orders for deferred retry when "
            "payment-service recovers"
        ),
        "api-gateway": (
            "14:32:20 WARN  Gateway: 8% of requests returning 5xx in last 60s "
            "(baseline < 0.5%)\n"
            "14:32:21 INFO  Gateway: Top error paths: POST /api/v2/checkout (42%), "
            "POST /api/v2/payments (38%)\n"
            "14:32:22 INFO  Gateway: Non-payment endpoints operating normally"
        ),
    },
    investigate_content={
        "payment-service": (
            "=== payment-service — Investigation Summary ===\n"
            "Team: commerce-team | Criticality: critical\n"
            "Role: Payment processing via Stripe and internal ledger\n"
            "Health: FAILING | Replicas: 3 | Version: v2.4.1\n"
            "Last deploy: 12 minutes ago (previous: v2.3.8)\n"
            "Depends on: primary-db\n"
            "Depended on by: order-service\n"
            "Recent incidents: None in last 30 days\n"
            "Deploy note: v2.4.1 upgraded Stripe SDK from v12 to v15 "
            "(breaking API change)\n"
            "Status: FAILING — strong correlation between deploy and error onset."
        ),
        "order-service": (
            "=== order-service — Investigation Summary ===\n"
            "Team: commerce-team | Criticality: high\n"
            "Role: Order lifecycle management\n"
            "Health: DEGRADED | Replicas: 3 | Version: v4.1.7\n"
            "Last deploy: 5 days ago\n"
            "Depends on: payment-service, inventory-service, notification-svc, primary-db\n"
            "Depended on by: api-gateway\n"
            "Recent incidents: None in last 30 days\n"
            "Status: Degraded — failures originate from payment-service dependency."
        ),
    },
    degradation_schedule=[
        DegradationEvent(15, "order-service", "failing", error_rate=0.32,
                         p99_latency_ms=2400, caused_by="payment-service"),
        DegradationEvent(25, "api-gateway", "failing", error_rate=0.18,
                         caused_by="payment-service"),
        DegradationEvent(35, "notification-svc", "degraded", error_rate=0.05,
                         caused_by="payment-service"),
    ],
    required_evidence=[
        "investigate:payment-service",
        "check_logs:payment-service",
    ],
)

# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 2 — MEDIUM: Database Connection Exhaustion
# ═══════════════════════════════════════════════════════════════════════════

MEDIUM_DB_CONN_LEAK = ScenarioTemplate(
    name="2_medium_db_conn_leak",
    description=(
        "Primary database connection pool nearly exhausted. "
        "Symptoms appear at the database level, but root cause is a "
        "connection leak in user-service after a recent deploy."
    ),
    difficulty="medium",
    severity="P1",
    sla_minutes=45,
    investigation_budget=100.0,
    incident_summary=(
        "PagerDuty alert: primary-db connection pool at 95% utilization, CPU 92%. "
        "auth-service and api-gateway showing elevated error rates. "
        "Multiple services dependent on primary-db may become unavailable."
    ),
    initial_overrides={
        "primary-db": {
            "health": "degraded", "error_rate": 0.02, "p99_latency_ms": 850,
            "cpu_percent": 92.0, "memory_percent": 78.0, "qps": 22000,
            "replicas": 2, "last_deploy": "45 days ago", "version": "v15.4",
        },
        "user-service": {
            "health": "degraded", "error_rate": 0.12, "p99_latency_ms": 1500,
            "cpu_percent": 30.0, "memory_percent": 55.0, "qps": 4100,
            "replicas": 3, "last_deploy": "35 minutes ago", "version": "v3.1.0",
        },
        "auth-service": {
            "health": "degraded", "error_rate": 0.10, "p99_latency_ms": 420,
            "cpu_percent": 25.0, "memory_percent": 38.0, "qps": 6200,
            "replicas": 3, "last_deploy": "10 days ago", "version": "v3.8.1",
        },
        "api-gateway": {
            "health": "degraded", "error_rate": 0.06, "p99_latency_ms": 280,
            "cpu_percent": 45.0, "memory_percent": 44.0, "qps": 8500,
            "replicas": 6, "last_deploy": "7 days ago", "version": "v5.2.0",
        },
    },
    root_causes=[
        RootCause("user-service", "rollback",
                  "Version v3.1.0 introduced a connection leak in "
                  "UserProfileV2Handler — connections opened but never returned "
                  "to the pool"),
    ],
    alerts=[
        {"severity": "CRITICAL", "service": "primary-db",
         "message": "Connection pool 95% utilized (threshold 80%) — CPU 92%"},
        {"severity": "WARNING", "service": "auth-service",
         "message": "Error rate 10% — threshold 5%"},
        {"severity": "WARNING", "service": "api-gateway",
         "message": "Error rate 6% — threshold 2%"},
        {"severity": "INFO", "service": "user-service",
         "message": "Deployed v3.1.0 35 minutes ago"},
    ],
    log_content={
        "primary-db": (
            "14:45:01 WARN  PostgreSQL: connection pool utilization at 95% "
            "(95/100 active connections)\n"
            "14:45:02 WARN  PostgreSQL: 12 queries waiting for available connection\n"
            "14:45:03 ERROR PostgreSQL: connection timeout for client at 10.0.3.12 "
            "(user-service pod-7)\n"
            "14:45:05 WARN  PostgreSQL: Top connection consumers: user-service=47, "
            "auth-service=18, order-service=12, search-service=8\n"
            "14:45:06 INFO  PostgreSQL: Slow query log: 23 queries exceeded 500ms "
            "in last 60s"
        ),
        "user-service": (
            "14:44:50 WARN  ConnectionPool: Pool size grew from 12 to 47 active "
            "connections in last 30 minutes\n"
            "14:44:51 ERROR ConnectionPool: Detected 31 connections held > 120s "
            "without activity (possible leak)\n"
            "14:44:52 WARN  UserRepository: Query completed but connection not "
            "returned to pool in UserProfileV2Handler\n"
            "14:44:53 INFO  DeployTracker: Current version v3.1.0 deployed "
            "35 minutes ago (previous: v3.0.9)\n"
            "14:44:54 DEBUG UserRepository: New connection opened (total active: 48), "
            "stack trace: UserProfileV2Handler.getProfile() line 142"
        ),
        "auth-service": (
            "14:45:10 WARN  AuthValidator: Database queries timing out intermittently "
            "— 10% of token validations failing\n"
            "14:45:11 ERROR AuthValidator: Connection pool wait exceeded 5000ms, "
            "request failed\n"
            "14:45:12 INFO  AuthValidator: Falling back to cached sessions for "
            "12 requests"
        ),
        "api-gateway": (
            "14:45:20 WARN  Gateway: Elevated 5xx rate — 6% of requests failing\n"
            "14:45:21 INFO  Gateway: Top error paths: GET /api/v2/profile (35%), "
            "POST /api/v2/auth/token (28%)\n"
            "14:45:22 INFO  Gateway: Order and search endpoints unaffected"
        ),
    },
    investigate_content={
        "primary-db": (
            "=== primary-db — Investigation Summary ===\n"
            "Team: database-team | Criticality: critical\n"
            "Role: PostgreSQL primary database for all transactional data\n"
            "Health: DEGRADED | Replicas: 2 | Version: v15.4\n"
            "Last deploy: 45 days ago — no recent changes\n"
            "Depends on: none\n"
            "Depended on by: auth-service, user-service, order-service, "
            "payment-service, inventory-service, search-service, notification-svc\n"
            "Connection pool: 95/100 connections in use\n"
            "Top consumers: user-service (47 conns), auth-service (18 conns)\n"
            "Status: Overloaded — connection pool near exhaustion, "
            "but no database-side bugs. External pressure suspected."
        ),
        "user-service": (
            "=== user-service — Investigation Summary ===\n"
            "Team: accounts-team | Criticality: high\n"
            "Role: User profiles, preferences, and account management\n"
            "Health: DEGRADED | Replicas: 3 | Version: v3.1.0\n"
            "Last deploy: 35 minutes ago (previous: v3.0.9)\n"
            "Depends on: primary-db, cache-layer\n"
            "Depended on by: api-gateway, auth-service, notification-svc\n"
            "v3.1.0 changelog: Added new UserProfileV2Handler with "
            "direct DB queries (bypasses connection pooling wrapper)\n"
            "Status: DEGRADED — holding 47 database connections (normal: 8-12). "
            "Strong correlation between v3.1.0 deploy and connection growth."
        ),
        "auth-service": (
            "=== auth-service — Investigation Summary ===\n"
            "Team: platform-team | Criticality: critical\n"
            "Role: Authentication and authorization\n"
            "Health: DEGRADED | Replicas: 3 | Version: v3.8.1\n"
            "Last deploy: 10 days ago — no recent changes\n"
            "Depends on: user-service, cache-layer, primary-db\n"
            "Depended on by: api-gateway\n"
            "Status: Degraded due to upstream dependency issues. "
            "No auth-service-specific bugs detected."
        ),
    },
    degradation_schedule=[
        DegradationEvent(10, "primary-db", "failing", error_rate=0.08,
                         p99_latency_ms=2200, cpu_percent=97.0,
                         caused_by="user-service"),
        DegradationEvent(15, "auth-service", "failing", error_rate=0.25,
                         p99_latency_ms=3800, caused_by="user-service"),
        DegradationEvent(20, "api-gateway", "failing", error_rate=0.15,
                         caused_by="user-service"),
        DegradationEvent(25, "order-service", "degraded", error_rate=0.10,
                         p99_latency_ms=800, caused_by="user-service"),
        DegradationEvent(30, "payment-service", "degraded", error_rate=0.08,
                         caused_by="user-service"),
    ],
    required_evidence=[
        "investigate:primary-db",
        "check_logs:primary-db",
        "investigate:user-service",
        "check_logs:user-service",
    ],
)

# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 3 — HARD: Two Simultaneous Failures
# ═══════════════════════════════════════════════════════════════════════════

HARD_DUAL_FAILURE = ScenarioTemplate(
    name="3_hard_dual_failure",
    description=(
        "Two independent failures occurring simultaneously: a traffic spike on "
        "search-service requires scaling, and a bad deploy on inventory-service "
        "requires rollback. Both must be fixed to fully resolve the incident."
    ),
    difficulty="hard",
    severity="P1",
    sla_minutes=40,
    investigation_budget=100.0,
    incident_summary=(
        "Multiple PagerDuty alerts firing simultaneously. search-service latency "
        "critical (5200ms p99) with 98% CPU. inventory-service error rate at 35%. "
        "order-service and api-gateway both degraded. This appears to be a "
        "multi-vector incident."
    ),
    initial_overrides={
        "search-service": {
            "health": "failing", "error_rate": 0.05, "p99_latency_ms": 5200,
            "cpu_percent": 98.0, "memory_percent": 85.0, "qps": 15200,
            "replicas": 4, "last_deploy": "12 days ago", "version": "v2.9.0",
        },
        "inventory-service": {
            "health": "failing", "error_rate": 0.35, "p99_latency_ms": 3100,
            "cpu_percent": 45.0, "memory_percent": 55.0, "qps": 2700,
            "replicas": 3, "last_deploy": "8 minutes ago", "version": "v4.2.0",
        },
        "order-service": {
            "health": "degraded", "error_rate": 0.18, "p99_latency_ms": 1600,
            "cpu_percent": 52.0, "memory_percent": 50.0, "qps": 3200,
            "replicas": 3, "last_deploy": "5 days ago", "version": "v4.1.7",
        },
        "api-gateway": {
            "health": "degraded", "error_rate": 0.12, "p99_latency_ms": 420,
            "cpu_percent": 55.0, "memory_percent": 48.0, "qps": 8500,
            "replicas": 6, "last_deploy": "7 days ago", "version": "v5.2.0",
        },
        "cache-layer": {
            "health": "degraded", "error_rate": 0.008, "p99_latency_ms": 15,
            "cpu_percent": 88.0, "memory_percent": 72.0, "qps": 48000,
            "replicas": 4, "last_deploy": "30 days ago", "version": "v7.0.3",
        },
    },
    root_causes=[
        RootCause("search-service", "scale",
                  "Marketing flash-sale campaign drove 5x traffic spike"),
        RootCause("inventory-service", "rollback",
                  "Version v4.2.0 references a DB migration that was never applied"),
    ],
    alerts=[
        {"severity": "CRITICAL", "service": "search-service",
         "message": "p99 latency 5200ms (threshold 200ms) — CPU 98%"},
        {"severity": "CRITICAL", "service": "inventory-service",
         "message": "Error rate 35% — threshold 5%"},
        {"severity": "WARNING", "service": "order-service",
         "message": "Error rate 18% — threshold 5%"},
        {"severity": "WARNING", "service": "api-gateway",
         "message": "Error rate 12% — threshold 2%"},
        {"severity": "WARNING", "service": "cache-layer",
         "message": "CPU 88% — threshold 80%"},
    ],
    log_content={
        "search-service": (
            "14:50:01 WARN  SearchEngine: QPS surge detected — 15,247 req/s "
            "(baseline: 3,100 req/s)\n"
            "14:50:02 ERROR SearchEngine: Query queue depth exceeded 500 — "
            "rejecting new queries\n"
            "14:50:03 WARN  SearchEngine: All 4 replicas at > 95% CPU, "
            "index rebuilds paused\n"
            "14:50:04 INFO  TrafficAnalysis: Spike correlates with marketing "
            "campaign 'FLASH_SALE_2025' that went live at 14:42\n"
            "14:50:05 WARN  SearchEngine: Estimated capacity needed: "
            "12 replicas (current: 4)"
        ),
        "inventory-service": (
            "14:50:10 ERROR InventoryManager: SQL syntax error in "
            "getAvailableStock — column 'warehouse_zone' does not exist\n"
            "14:50:11 ERROR InventoryManager: Failed to check stock for "
            "SKU-44821: relation 'inventory_v2' does not exist\n"
            "14:50:12 WARN  InventoryManager: 35% of stock queries failing "
            "since deploy v4.2.0\n"
            "14:50:13 INFO  DeployTracker: Current version v4.2.0 deployed "
            "8 minutes ago (previous: v4.1.7)\n"
            "14:50:14 ERROR InventoryManager: Database migration "
            "047_add_warehouse_zones was NOT applied before deploy"
        ),
        "order-service": (
            "14:50:20 WARN  OrderProcessor: inventory-service returning 500 "
            "for 35% of stock checks\n"
            "14:50:21 ERROR OrderProcessor: Cannot confirm stock for order "
            "#91002 — inventory unavailable\n"
            "14:50:22 WARN  OrderProcessor: Fallback to cached stock levels "
            "for 12 orders (cache may be stale)"
        ),
        "cache-layer": (
            "14:50:30 WARN  CacheManager: CPU utilization 88% — approaching "
            "capacity\n"
            "14:50:31 INFO  CacheManager: Elevated traffic from search-service "
            "causing cache-miss storms\n"
            "14:50:32 INFO  CacheManager: Eviction rate increased 3x in last "
            "10 minutes"
        ),
        "api-gateway": (
            "14:50:40 WARN  Gateway: 12% of requests returning 5xx\n"
            "14:50:41 INFO  Gateway: Error breakdown — /api/v2/search (45%), "
            "/api/v2/orders (30%), /api/v2/inventory (25%)\n"
            "14:50:42 INFO  Gateway: Auth and user endpoints unaffected"
        ),
    },
    investigate_content={
        "search-service": (
            "=== search-service — Investigation Summary ===\n"
            "Team: discovery-team | Criticality: high\n"
            "Role: Product search, filtering, and recommendation engine\n"
            "Health: FAILING | Replicas: 4 | Version: v2.9.0\n"
            "Last deploy: 12 days ago — no recent code changes\n"
            "Depends on: primary-db, cache-layer\n"
            "Depended on by: api-gateway\n"
            "Current QPS: 15,247 (normal baseline: 3,100)\n"
            "Traffic source: Marketing campaign 'FLASH_SALE_2025'\n"
            "Status: FAILING — infrastructure bottleneck, not a code bug. "
            "Needs horizontal scaling to handle 5x traffic."
        ),
        "inventory-service": (
            "=== inventory-service — Investigation Summary ===\n"
            "Team: commerce-team | Criticality: high\n"
            "Role: Real-time stock levels and warehouse management\n"
            "Health: FAILING | Replicas: 3 | Version: v4.2.0\n"
            "Last deploy: 8 minutes ago (previous: v4.1.7)\n"
            "Depends on: primary-db, cache-layer\n"
            "Depended on by: order-service\n"
            "v4.2.0 changelog: Added warehouse zone partitioning — "
            "requires migration 047_add_warehouse_zones\n"
            "Status: FAILING — deploy v4.2.0 references DB schema that "
            "does not exist. Migration was not run before deploy."
        ),
        "order-service": (
            "=== order-service — Investigation Summary ===\n"
            "Team: commerce-team | Criticality: high\n"
            "Role: Order lifecycle management\n"
            "Health: DEGRADED | Replicas: 3 | Version: v4.1.7\n"
            "Last deploy: 5 days ago — no recent code changes\n"
            "Depends on: payment-service, inventory-service, notification-svc, "
            "primary-db\n"
            "Depended on by: api-gateway\n"
            "Status: Degraded — affected by inventory-service failures. "
            "No order-service-specific bugs."
        ),
    },
    degradation_schedule=[
        DegradationEvent(8, "order-service", "failing", error_rate=0.30,
                         p99_latency_ms=2800, caused_by="inventory-service"),
        DegradationEvent(12, "api-gateway", "failing", error_rate=0.22,
                         caused_by="search-service"),
        DegradationEvent(18, "cache-layer", "failing", cpu_percent=96.0,
                         error_rate=0.02, caused_by="search-service"),
        DegradationEvent(22, "notification-svc", "degraded", error_rate=0.06,
                         caused_by="inventory-service"),
    ],
    required_evidence=[
        "investigate:search-service",
        "check_logs:search-service",
        "investigate:inventory-service",
        "check_logs:inventory-service",
    ],
)

# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 4 — FRONTIER: Misleading Cache Corruption
# ═══════════════════════════════════════════════════════════════════════════

FRONTIER_CACHE_CORRUPTION = ScenarioTemplate(
    name="4_frontier_cache_corruption",
    description=(
        "Multiple services showing intermittent failures, but the cache layer "
        "appears completely healthy on all metrics. The real root cause is "
        "silent cache data corruption — stale data being served as fresh."
    ),
    difficulty="frontier",
    severity="P1",
    sla_minutes=50,
    investigation_budget=100.0,
    incident_summary=(
        "Unusual incident pattern: auth-service, inventory-service, and "
        "search-service are all showing elevated error rates simultaneously, "
        "but none of them have had recent deploys. No single service appears "
        "to be the clear root cause. Customer reports of stale data, incorrect "
        "prices, and intermittent login failures."
    ),
    initial_overrides={
        # cache-layer looks HEALTHY — that's the trap
        "cache-layer": {
            "health": "healthy", "error_rate": 0.001, "p99_latency_ms": 2,
            "cpu_percent": 45.0, "memory_percent": 62.0, "qps": 42000,
            "replicas": 4, "last_deploy": "30 days ago", "version": "v7.0.3",
        },
        "auth-service": {
            "health": "degraded", "error_rate": 0.08, "p99_latency_ms": 340,
            "cpu_percent": 22.0, "memory_percent": 38.0, "qps": 6200,
            "replicas": 3, "last_deploy": "10 days ago", "version": "v3.8.1",
        },
        "inventory-service": {
            "health": "degraded", "error_rate": 0.12, "p99_latency_ms": 280,
            "cpu_percent": 25.0, "memory_percent": 40.0, "qps": 2700,
            "replicas": 3, "last_deploy": "14 days ago", "version": "v4.1.7",
        },
        "search-service": {
            "health": "degraded", "error_rate": 0.10, "p99_latency_ms": 410,
            "cpu_percent": 42.0, "memory_percent": 56.0, "qps": 3100,
            "replicas": 4, "last_deploy": "12 days ago", "version": "v2.9.0",
        },
        "api-gateway": {
            "health": "degraded", "error_rate": 0.07, "p99_latency_ms": 220,
            "cpu_percent": 38.0, "memory_percent": 43.0, "qps": 8500,
            "replicas": 6, "last_deploy": "7 days ago", "version": "v5.2.0",
        },
    },
    root_causes=[
        RootCause("cache-layer", "restart",
                  "Shard 7 replication is 4 hours behind due to a silent "
                  "compaction failure — serving stale data across auth, "
                  "inventory, and search"),
    ],
    alerts=[
        {"severity": "WARNING", "service": "auth-service",
         "message": "Error rate 8% — threshold 5%"},
        {"severity": "WARNING", "service": "inventory-service",
         "message": "Error rate 12% — threshold 5%"},
        {"severity": "WARNING", "service": "search-service",
         "message": "Error rate 10% — threshold 5%"},
        {"severity": "WARNING", "service": "api-gateway",
         "message": "Error rate 7% — threshold 2%"},
        {"severity": "INFO", "service": "cache-layer",
         "message": "All metrics within normal range — no anomalies detected"},
    ],
    log_content={
        "auth-service": (
            "14:55:01 WARN  AuthValidator: Session token for user #8823 validated "
            "by cache but REJECTED by database — cache says role=admin, DB says "
            "role=viewer (stale cache entry)\n"
            "14:55:02 ERROR AuthValidator: Permission check inconsistency — "
            "cache returned outdated ACL set (cache_version=3, db_version=7)\n"
            "14:55:03 WARN  AuthValidator: Forced DB fallback for 3 requests "
            "due to cache/DB mismatch in last 60s\n"
            "14:55:04 WARN  AuthValidator: User #12841 session shows "
            "created_at=2024-12-01 in cache, but record was deleted from DB "
            "on 2025-01-10"
        ),
        "inventory-service": (
            "14:55:10 WARN  StockChecker: Cache returned quantity=150 for "
            "SKU-22019 but DB shows quantity=0 (sold out 2 hours ago)\n"
            "14:55:11 ERROR StockChecker: Order #94210 accepted based on cached "
            "stock level, but inventory reservation FAILED (actual stock: 0)\n"
            "14:55:12 WARN  StockChecker: 8 oversell incidents in last 15 minutes "
            "— all involve cached stock levels diverging from DB\n"
            "14:55:13 WARN  StockChecker: Cache TTL for inventory keys is set to "
            "3600s but data appears stale BEYOND TTL"
        ),
        "search-service": (
            "14:55:30 WARN  SearchIndex: Cached product metadata for product "
            "#7721 shows price=$29.99 but DB shows price=$39.99 "
            "(updated 3 hours ago)\n"
            "14:55:31 WARN  SearchIndex: Search results inconsistency — "
            "12 products showing outdated prices from cache\n"
            "14:55:32 ERROR SearchIndex: Customer complaint: product listed as "
            "'in stock' on search results but checkout shows 'out of stock'"
        ),
        "cache-layer": (
            "14:55:20 INFO  CacheManager: Serving 45,231 keys across 16 shards, "
            "hit_rate=98.5%\n"
            "14:55:21 INFO  CacheManager: Memory: 2.48GB / 4.00GB (62.0%)\n"
            "14:55:22 DEBUG CacheManager: Background compaction completed in "
            "0.8s, 0 keys evicted\n"
            "14:55:23 DEBUG CacheManager: Shard 7 last full sync: 4 hours ago "
            "(sync_interval=1h — OVERDUE)\n"
            "14:55:24 WARN  CacheManager: Shard 7 replication lag: 14,231 ops "
            "behind primary (threshold: 1,000)"
        ),
        "api-gateway": (
            "14:55:40 WARN  Gateway: 7% of requests returning mixed "
            "success/failure across multiple backends\n"
            "14:55:41 INFO  Gateway: Affected endpoints span auth, inventory, "
            "and search — no single backend is the primary source\n"
            "14:55:42 INFO  Gateway: Error pattern is intermittent, not "
            "consistent — suggests data-dependent failures"
        ),
    },
    investigate_content={
        "cache-layer": (
            "=== cache-layer — Investigation Summary ===\n"
            "Team: platform-team | Criticality: critical\n"
            "Role: Shared Redis caching layer for sessions, stock, and queries\n"
            "Health: HEALTHY | Replicas: 4 | Version: v7.0.3\n"
            "Last deploy: 30 days ago — no recent changes\n"
            "Depends on: none\n"
            "Depended on by: auth-service, user-service, inventory-service, "
            "search-service\n"
            "Metrics: error_rate=0.1%, p99=2ms, CPU=45%, memory=62%\n"
            "Sharding: 16 shards, shard 7 replication lag=14,231 ops (4h behind)\n"
            "Status: Metrics appear healthy but shard 7 sync is severely "
            "overdue — possible stale data being served."
        ),
        "auth-service": (
            "=== auth-service — Investigation Summary ===\n"
            "Team: platform-team | Criticality: critical\n"
            "Role: Authentication and authorization\n"
            "Health: DEGRADED | Replicas: 3 | Version: v3.8.1\n"
            "Last deploy: 10 days ago — no recent changes\n"
            "Depends on: user-service, cache-layer, primary-db\n"
            "Depended on by: api-gateway\n"
            "Error pattern: Cache/DB mismatches on session and ACL data\n"
            "Status: Degraded — errors are data-consistency failures, not "
            "code bugs. Cache is returning outdated records."
        ),
        "inventory-service": (
            "=== inventory-service — Investigation Summary ===\n"
            "Team: commerce-team | Criticality: high\n"
            "Role: Real-time stock levels and warehouse management\n"
            "Health: DEGRADED | Replicas: 3 | Version: v4.1.7\n"
            "Last deploy: 14 days ago — no recent changes\n"
            "Depends on: primary-db, cache-layer\n"
            "Depended on by: order-service\n"
            "Error pattern: Cached stock quantities diverge from DB, "
            "causing oversells\n"
            "Status: Degraded — not a code bug. Cached data is stale "
            "beyond configured TTL."
        ),
        "search-service": (
            "=== search-service — Investigation Summary ===\n"
            "Team: discovery-team | Criticality: high\n"
            "Role: Product search and recommendations\n"
            "Health: DEGRADED | Replicas: 4 | Version: v2.9.0\n"
            "Last deploy: 12 days ago — no recent changes\n"
            "Depends on: primary-db, cache-layer\n"
            "Depended on by: api-gateway\n"
            "Error pattern: Stale product prices and availability from cache\n"
            "Status: Degraded — cached product metadata is outdated. "
            "Same pattern as inventory-service."
        ),
    },
    degradation_schedule=[
        DegradationEvent(10, "auth-service", "failing", error_rate=0.18,
                         p99_latency_ms=520, caused_by="cache-layer"),
        DegradationEvent(15, "inventory-service", "failing", error_rate=0.25,
                         p99_latency_ms=400, caused_by="cache-layer"),
        DegradationEvent(20, "search-service", "failing", error_rate=0.20,
                         p99_latency_ms=680, caused_by="cache-layer"),
        DegradationEvent(25, "api-gateway", "failing", error_rate=0.18,
                         caused_by="cache-layer"),
        DegradationEvent(30, "order-service", "degraded", error_rate=0.12,
                         p99_latency_ms=900, caused_by="cache-layer"),
        DegradationEvent(35, "user-service", "degraded", error_rate=0.08,
                         caused_by="cache-layer"),
    ],
    required_evidence=[
        "check_logs:auth-service",
        "check_logs:inventory-service",
        "investigate:cache-layer",
        "check_logs:cache-layer",
    ],
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_SCENARIOS: dict[str, ScenarioTemplate] = {
    s.name: s
    for s in [
        EASY_PAYMENT_DEPLOY,
        MEDIUM_DB_CONN_LEAK,
        HARD_DUAL_FAILURE,
        FRONTIER_CACHE_CORRUPTION,
    ]
}
