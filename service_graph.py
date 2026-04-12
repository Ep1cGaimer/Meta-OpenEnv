"""
Microservice dependency graph for the Incident Response Environment.

Defines a realistic 10-service architecture with dependencies, default
healthy-state metrics, and helpers for graph traversal.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Health / Load level constants
# ---------------------------------------------------------------------------

HEALTH_LEVELS = ["healthy", "degraded", "failing", "down"]
LOAD_LEVELS = ["normal", "elevated", "high", "critical"]

HEALTH_SEVERITY = {"healthy": 0, "degraded": 1, "failing": 2, "down": 3}


# ---------------------------------------------------------------------------
# Graph data models
# ---------------------------------------------------------------------------

@dataclass
class ServiceNode:
    name: str
    team: str
    description: str
    default_replicas: int = 3
    criticality: str = "high"       # critical, high, medium

@dataclass
class ServiceDependency:
    from_service: str
    to_service: str
    protocol: str = "http"          # http, grpc, tcp
    criticality: str = "high"       # critical, high, medium


# ---------------------------------------------------------------------------
# Fixed service mesh topology
# ---------------------------------------------------------------------------

SERVICES: dict[str, ServiceNode] = {
    "api-gateway": ServiceNode(
        "api-gateway", "platform-team",
        "Public-facing API gateway routing all client traffic",
        default_replicas=6, criticality="critical",
    ),
    "auth-service": ServiceNode(
        "auth-service", "platform-team",
        "Authentication and authorization for every inbound request",
        criticality="critical",
    ),
    "user-service": ServiceNode(
        "user-service", "accounts-team",
        "User profiles, preferences, and account management",
    ),
    "order-service": ServiceNode(
        "order-service", "commerce-team",
        "Order lifecycle management: creation, fulfillment, tracking",
    ),
    "payment-service": ServiceNode(
        "payment-service", "commerce-team",
        "Payment processing via Stripe and internal ledger",
        criticality="critical",
    ),
    "inventory-service": ServiceNode(
        "inventory-service", "commerce-team",
        "Real-time stock levels and warehouse management",
    ),
    "search-service": ServiceNode(
        "search-service", "discovery-team",
        "Product search, filtering, and recommendation engine",
    ),
    "notification-svc": ServiceNode(
        "notification-svc", "platform-team",
        "Email, SMS, and push notification delivery",
        criticality="medium",
    ),
    "cache-layer": ServiceNode(
        "cache-layer", "platform-team",
        "Shared Redis caching layer for sessions, stock, and query results",
        default_replicas=4, criticality="critical",
    ),
    "primary-db": ServiceNode(
        "primary-db", "database-team",
        "PostgreSQL primary database for all transactional data",
        default_replicas=2, criticality="critical",
    ),
}

DEPENDENCIES: list[ServiceDependency] = [
    # api-gateway calls →
    ServiceDependency("api-gateway", "auth-service", "http", "critical"),
    ServiceDependency("api-gateway", "user-service", "http", "high"),
    ServiceDependency("api-gateway", "order-service", "http", "high"),
    ServiceDependency("api-gateway", "search-service", "http", "medium"),
    # auth-service calls →
    ServiceDependency("auth-service", "user-service", "grpc", "high"),
    ServiceDependency("auth-service", "cache-layer", "tcp", "high"),
    ServiceDependency("auth-service", "primary-db", "tcp", "critical"),
    # user-service calls →
    ServiceDependency("user-service", "primary-db", "tcp", "critical"),
    ServiceDependency("user-service", "cache-layer", "tcp", "high"),
    # order-service calls →
    ServiceDependency("order-service", "payment-service", "http", "critical"),
    ServiceDependency("order-service", "inventory-service", "http", "high"),
    ServiceDependency("order-service", "notification-svc", "http", "medium"),
    ServiceDependency("order-service", "primary-db", "tcp", "high"),
    # payment-service calls →
    ServiceDependency("payment-service", "primary-db", "tcp", "critical"),
    # inventory-service calls →
    ServiceDependency("inventory-service", "primary-db", "tcp", "critical"),
    ServiceDependency("inventory-service", "cache-layer", "tcp", "high"),
    # search-service calls →
    ServiceDependency("search-service", "primary-db", "tcp", "high"),
    ServiceDependency("search-service", "cache-layer", "tcp", "high"),
    # notification-svc calls →
    ServiceDependency("notification-svc", "user-service", "grpc", "medium"),
    ServiceDependency("notification-svc", "primary-db", "tcp", "medium"),
]

SERVICE_NAMES: list[str] = sorted(SERVICES.keys())

VALID_TEAMS: set[str] = {
    "platform-team", "accounts-team", "commerce-team",
    "discovery-team", "database-team", "security-team",
}


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def get_dependents(service_name: str) -> list[str]:
    """Services that CALL the given service (upstream callers)."""
    return [d.from_service for d in DEPENDENCIES if d.to_service == service_name]


def get_dependencies(service_name: str) -> list[str]:
    """Services that the given service CALLS (downstream callees)."""
    return [d.to_service for d in DEPENDENCIES if d.from_service == service_name]


def get_dependency_criticality(from_svc: str, to_svc: str) -> str:
    for d in DEPENDENCIES:
        if d.from_service == from_svc and d.to_service == to_svc:
            return d.criticality
    return "none"


# ---------------------------------------------------------------------------
# Default healthy-state data
# ---------------------------------------------------------------------------

DEFAULT_HEALTHY_METRICS: dict[str, dict] = {
    "api-gateway":       {"health": "healthy", "error_rate": 0.002, "p99_latency_ms": 48,   "cpu_percent": 32.0, "memory_percent": 41.0, "qps": 8500,  "replicas": 6, "last_deploy": "7 days ago",  "version": "v5.2.0"},
    "auth-service":      {"health": "healthy", "error_rate": 0.001, "p99_latency_ms": 22,   "cpu_percent": 18.0, "memory_percent": 35.0, "qps": 6200,  "replicas": 3, "last_deploy": "10 days ago", "version": "v3.8.1"},
    "user-service":      {"health": "healthy", "error_rate": 0.001, "p99_latency_ms": 30,   "cpu_percent": 15.0, "memory_percent": 38.0, "qps": 4100,  "replicas": 3, "last_deploy": "14 days ago", "version": "v3.0.9"},
    "order-service":     {"health": "healthy", "error_rate": 0.003, "p99_latency_ms": 65,   "cpu_percent": 28.0, "memory_percent": 45.0, "qps": 3200,  "replicas": 3, "last_deploy": "5 days ago",  "version": "v4.1.7"},
    "payment-service":   {"health": "healthy", "error_rate": 0.002, "p99_latency_ms": 120,  "cpu_percent": 22.0, "memory_percent": 42.0, "qps": 1800,  "replicas": 3, "last_deploy": "14 days ago", "version": "v2.3.8"},
    "inventory-service": {"health": "healthy", "error_rate": 0.001, "p99_latency_ms": 35,   "cpu_percent": 20.0, "memory_percent": 36.0, "qps": 2700,  "replicas": 3, "last_deploy": "14 days ago", "version": "v4.1.7"},
    "search-service":    {"health": "healthy", "error_rate": 0.002, "p99_latency_ms": 85,   "cpu_percent": 40.0, "memory_percent": 55.0, "qps": 3100,  "replicas": 4, "last_deploy": "12 days ago", "version": "v2.9.0"},
    "notification-svc":  {"health": "healthy", "error_rate": 0.001, "p99_latency_ms": 45,   "cpu_percent": 12.0, "memory_percent": 30.0, "qps": 900,   "replicas": 2, "last_deploy": "21 days ago", "version": "v1.4.2"},
    "cache-layer":       {"health": "healthy", "error_rate": 0.0005,"p99_latency_ms": 2,    "cpu_percent": 28.0, "memory_percent": 52.0, "qps": 42000, "replicas": 4, "last_deploy": "30 days ago", "version": "v7.0.3"},
    "primary-db":        {"health": "healthy", "error_rate": 0.0003,"p99_latency_ms": 8,    "cpu_percent": 35.0, "memory_percent": 60.0, "qps": 22000, "replicas": 2, "last_deploy": "45 days ago", "version": "v15.4"},
}


def default_investigate_text(service_name: str) -> str:
    """Return investigation text for a healthy service."""
    svc = SERVICES[service_name]
    deps = get_dependencies(service_name)
    dependents = get_dependents(service_name)
    m = DEFAULT_HEALTHY_METRICS[service_name]
    return (
        f"=== {service_name} — Investigation Summary ===\n"
        f"Team: {svc.team} | Criticality: {svc.criticality}\n"
        f"Role: {svc.description}\n"
        f"Health: {m['health']} | Replicas: {m['replicas']} | Version: {m['version']}\n"
        f"Last deploy: {m['last_deploy']}\n"
        f"Depends on: {', '.join(deps) if deps else 'none'}\n"
        f"Depended on by: {', '.join(dependents) if dependents else 'none (leaf)'}\n"
        f"Recent incidents: None in last 30 days\n"
        f"Alert history: No alerts in last 24 hours\n"
        f"Status: Operating normally within all thresholds."
    )


def default_log_text(service_name: str) -> str:
    """Return log output for a fully healthy service."""
    return (
        f"14:30:01 INFO  {service_name}: Health check passed — all dependencies responsive\n"
        f"14:30:02 INFO  {service_name}: Request processing normal, 0 errors in last 60s\n"
        f"14:30:03 DEBUG {service_name}: Avg latency 12ms, p99 18ms, queue depth 0\n"
        f"14:30:04 INFO  {service_name}: No anomalies detected"
    )
