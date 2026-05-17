# ADR-003: Event-logged architecture, not distributed event-driven

**Status:** Accepted  
**Date:** 2026-05-17  
**Deciders:** Human Founder  
**Related to Objective:** OBJ-001

---

## Context

AQCS requires observability, auditability, and a structured record of system activity. The dominant industry pattern for this is an event-driven architecture with a message broker (Kafka, Redis Streams, RabbitMQ, etc.).

However, AQCS in Phase 1 is a single-process research system running batch workloads on a local machine or a single server. There are no microservices, no independent scaling requirements, and no need for distributed delivery guarantees.

The question requiring a formal decision is: how should events be structured and dispatched?

## Decision

**AQCS uses an event-logged architecture, not a distributed event-driven architecture.**

Events are typed, immutable Pydantic records dispatched synchronously via an in-process `EventBus`. There is no message broker, no async queue, no replay mechanism, and no distributed delivery. Event storage in Phase 1 is via structlog JSON logs only.

The `EventBus`:
- Is synchronous
- Has no global singleton (dependency injection only)
- Isolates handler exceptions (one failing handler does not crash others)
- Has no persistence, replay, or delivery guarantee
- May be extended with a JSONL-writer handler by callers who need durable event storage

This decision is intentional and not a temporary limitation to be "fixed later." The complexity of a distributed event system is unjustified until AQCS has independent services with independent scaling needs.

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| Kafka | Requires a broker process, ZooKeeper or KRaft, consumer groups, topic management. Massive operational overhead for a single-process system. |
| Redis Streams | Requires a Redis server. Adds a network dependency and operational burden for no gain. |
| Python asyncio | Adds async complexity throughout the codebase for no benefit in a batch processing system. |
| Celery | Task queue for distributed background jobs — not what events are for. Wrong abstraction. |
| SQLite event store | Adds a persistence dependency. Phase 1 does not require event replay. |
| No events at all | Loses auditability and LLM Oversight capability. Not acceptable for an institutional platform. |

## Consequences

**Positive:**
- Zero infrastructure dependencies for the event system
- Fully synchronous and debuggable — no concurrency hazards
- Trivial to test (no broker to mock)
- Events are available immediately for LLM Oversight without any delay
- Adding a durable JSONL writer is a one-function change

**Negative:**
- No delivery guarantees — if a handler crashes, the event is not retried
- No replay capability — historical events cannot be replayed from a broker
- Not suitable for multi-process or distributed deployment without refactoring

**Neutral:**
- Phase 3+ (live execution) may require a more durable event transport if independent processes are introduced. This decision does not prevent that evolution — the `EventBus` interface is a clean abstraction point for replacement.

## Related documents

- `docs/architecture/event-schema.md`
- `src/aqcs/utils/event_bus.py`
- `src/aqcs/utils/events.py`
- ADR-002: Quant Core determinism and LLM Oversight boundary
