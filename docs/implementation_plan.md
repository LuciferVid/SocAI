# Free Deployment (Lite Mode) Implementation Plan

This plan outlines the steps to make the project compatible with **Free Tier** hosting (Render/Railway) by replacing Kafka with Redis for messaging, significantly reducing RAM usage.

## User Review Required

> [!NOTE]
> We are using **Redis Pub/Sub** instead of Kafka for the "Free Tier" version. This saves ~1.5GB of RAM while keeping the real-time streaming functionality intact.

## Proposed Changes

### Messaging Abstraction
#### [NEW] [messaging.py](file:///Users/vid/Desktop/projectai/app/services/messaging.py)
- Create a unified interface for `produce` and `consume` that can swap between Kafka and Redis.

#### [MODIFY] [kafka_producer.py](file:///Users/vid/Desktop/projectai/app/services/kafka_producer.py) & [kafka_consumer.py](file:///Users/vid/Desktop/projectai/app/services/kafka_consumer.py)
- Refactor to use the new messaging interface.
- Add Redis support (Pub/Sub).

### Configuration
#### [MODIFY] [settings.py](file:///Users/vid/Desktop/projectai/config/settings.py)
- Add `MESSAGING_TYPE` (kafka/redis) flag.

### Deployment (Render)
#### [NEW] [render.yaml](file:///Users/vid/Desktop/projectai/render.yaml)
- Define a "Blueprint" containing:
  - **App Service** (FastAPI)
  - **Postgres** (Managed Free)
  - **Redis** (Managed Free)
  - **Generator** (Background worker)

## Verification Plan

### Automated Tests
- Run `pytest tests/test_messaging.py` to ensure Redis swap works.

### Manual Verification
- Deploy to Render via Blueprint.
- Verify dashboard updates in real-time.
