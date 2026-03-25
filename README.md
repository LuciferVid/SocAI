# SocAI: AI Threat Detection System (Mini SOC) 🛡️

A real-time, streaming AI-powered Security Operations Center. It ingests logs via **Redis Pub/Sub**, scores them with **ML anomaly detection models**, fires instant alerts, and surfaces everything on a **live dashboard**.

## Architecture

```text
Network/Host Sensors → Redis Pub/Sub (ingestion) → Worker → Feature Engine → ML Scorer → PostgreSQL
                                                                        ↓
                                                                Alert Dispatcher → Webhook / Email
                                                                        ↓
                                                                Dashboard (WebSocket)
```

### Key Design Decisions

| Decision              | Rationale                                                                                 |
| --------------------- | ----------------------------------------------------------------------------------------- |
| **Redis Pub/Sub**     | Ultra-low latency ingestion, designed for high-throughput enterprise environments.        |
| **Redis Sorted Sets** | O(log N) sliding-window queries for real-time feature engineering.                        |
| **Hybrid ML + Rules** | Deterministic rules catch known attacks (Brute Force, DDoS); ML isolates novel anomalies. |
| **EWMA Reputation**   | Exponentially Weighted Moving Average for dynamic IP reputation scoring.                  |
| **Hot-Swap Models**   | Scorer reloads ML artifacts on-the-fly without service interruption.                      |

## Tech Stack

- **Backend**: FastAPI (Python 3.11)
- **Streaming**: Redis Pub/Sub
- **ML**: scikit-learn (Isolation Forest) + PyTorch (Autoencoder)
- **Storage**: PostgreSQL 16 + Redis 7
- **Dashboard**: Vanilla HTML/JS + Chart.js
- **Infra**: Docker Compose

## ML Detection Strategy

| Phase | Model                | How it works                                                                            |
| ----- | -------------------- | --------------------------------------------------------------------------------------- |
| 1     | **Isolation Forest** | Unsupervised anomaly scoring — isolates outliers in multidimensional space.             |
| 2     | **Autoencoder**      | Neural network reconstruction error — high error signals a "never-before-seen" pattern. |
| 3     | **Hybrid Engine**    | Weighted ensemble of ML scores + Rule-based logic for specific attack types.            |

## Feature Engineering (Real-Time)

| Feature            | Description                                                        |
| ------------------ | ------------------------------------------------------------------ |
| `ip_req_count_1m`  | Request frequency per IP in 60s windows.                           |
| `ip_fail_count_1m` | Error rate (4xx/5xx) tracking for discovery/brute-force detection. |
| `unique_paths_1m`  | Number of distinct endpoints touched by a single IP.               |
| `burst_rate`       | Peak requests per second (5s sliding window).                      |
| `is_auth_endpoint` | Binary flag for high-value targets (login/admin).                  |

## Quick Start

### 1. Start Infrastructure

```bash
docker compose up -d
```

### 2. Setup Python environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Initialize ML Models

```bash
python -m app.ml.train
```

_This generates initial training data and saves model artifacts to `app/ml/artifacts/`._

### 4. Launch SOC

```bash
# Start API (Worker runs as a background task within the API process)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Start Network Sensor Agent (Separate Terminal)
python -m generator.sensor_agent
```

### 5. Access Dashboard

Navigate to **[http://localhost:8000](http://localhost:8000)** to see the SOCAI platform and live dashboard.

---

## Learning Path: How to Build This as a 2nd Year Student

This project synthesizes concepts from multiple CS domains. Here's a realistic learning journey:

### Core Prerequisites (learned in 1st-2nd year)

- **Python fundamentals** - OOP, decorators, async/await
- **SQL basics** - Schema design, queries, relationships
- **Web frameworks** - FastAPI, HTTP, REST APIs
- **Data structures** - Arrays, hash maps (for O(log N) understanding)

### Key Concepts Learned While Building

1. **Redis Data Structures**
   - Start: "What's a cache?" → Memcached or Redis
   - Depth: Sorted sets (ZADD, ZRANGEBYSCORE) for sliding windows
   - Reference: Redis official docs, 2-3 hours practice

2. **Async I/O with Python**
   - Why: Database connections block → use asyncio
   - Practice: Async FastAPI endpoints, SQLAlchemy + asyncpg
   - Time investment: ~1 week of practical coding

3. **ML Anomaly Detection**
   - Start: "What's outlier detection?" → scikit-learn tutorial
   - Isolation Forest: Read paper, use sklearn implementation (no training needed)
   - Autoencoder: PyTorch basics, reconstruction error concept
   - Time: 2-3 weeks to understand + implement

4. **Real-Time Streaming**
   - Problem: How to process 100 events/sec?
   - Solution: Background worker task (FastAPI lifespan context)
   - Don't need Kafka for prototypes — Redis Pub/Sub is simpler

5. **DevOps Essentials**
   - Docker basics (containers, compose)
   - Environment variables, secrets management
   - Deployment to free tier (Render, Railway)

### Why This is Realistic for a 2nd Year Student

- **Not starting from zero** - DS/DSA/Web courses provide foundation
- **Incremental complexity** - Start with a simple API, add features
- **Open-source leverage** - FastAPI, scikit-learn, PyTorch do the heavy lifting
- **Learning by building** - Each feature teaches something new
- **Months, not days** - This is a semester/summer project

### Resources Used

- FastAPI docs
- Redis docs (sorted sets guide)
- scikit-learn Isolation Forest
- PyTorch tutorials
- Stackoverflow + ChatGPT for debugging

---

**© 2026 SOCAI Inc. Proprietary and Confidential.**
