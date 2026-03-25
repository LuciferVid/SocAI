# SocAI: Architecture Evolution & Implementation

This document outlines the design decisions and technical challenges encountered while building a real-time threat detection system.

## Key Architectural Decisions

### 1. **Streaming with Redis Pub/Sub**

Initially considered Kafka for enterprise-grade streaming, but chose Redis Pub/Sub for:

- **Simplicity** - Single binary, built-in persistence, lower operational overhead
- **Cost** - Free-tier deployments (Render) provide Redis without separate Kafka cluster
- **Real-time features** - Redis sorted sets enable O(log N) sliding-window queries for feature engineering
- **Embedded worker** - No need for separate consumer group management

This trade-off accepts higher throughput limits but gains developer velocity for a prototype.

### 2. **Async/Await with SQLAlchemy**

Used asyncpg + async SQLAlchemy for:

- Non-blocking I/O during database operations (critical for 60+ second Render startup)
- Concurrent request handling without thread pools
- Better resource utilization on free-tier hosting

### 3. **Dual ML Approach (Hybrid Scoring)**

Rather than a single model:

- **Isolation Forest** - Fast, unseeded anomaly detection (Phase 1)
- **Autoencoder** - Learns reconstruction patterns, catches novel attacks (Phase 2)
- **Rule Engine** - Deterministic brute-force & DDoS detection (Phase 3)

Hybrid approach ensures both known and unknown attack patterns are detected without excessive false positives.

## Implementation Lessons

### Streaming Pipeline

The core challenge was ingesting logs → extracting features → scoring → persisting without bottlenecks.

Solution: Background worker task that consumes from Redis, maintains sliding-window aggregates in Redis (sorted sets), extracts features on-demand, and scores with reloadable models.

### Model Reloading

Instead of restarting the service for model updates, implemented **hot-swap reload** via `/api/retrain` endpoint:

1. Trigger retraining with new labeled data
2. Save models to disk
3. Main scorer reloads without downtime

### Feature Engineering

Real-time feature extraction required:

- Sliding-window counters (1m, 5m, 15m)
- Per-IP request frequency and error rates
- Burst detection (requests/sec)

Used Redis sorted sets with timestamp scores for O(log N) range queries instead of polling PostgreSQL.

## Deployment on Render

### Free Tier Constraints

- Single-threaded Python on free tier
- PostgreSQL boot time can exceed 50 seconds
- Added retry loop to wait for database availability

### Production Considerations

For enterprise deployment:

- Switch to managed Kafka for higher throughput
- Add dedicated ML inference service (GPU-accelerated)
- Implement multi-region failover
- Use time-series database (ClickHouse / Timescale) for metrics
