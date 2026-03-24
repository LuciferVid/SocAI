# AI Threat Detection System (Mini SOC) 
A real-time, streaming AI-powered Security Operations Center that ingests logs via **Apache Kafka**, scores them with **ML anomaly detection models**, fires instant alerts, and surfaces everything on a **live dashboard**.

## Architecture

```
Fake Logs → Kafka (logs.raw) → Parser → Feature Engine (Redis) → ML Scorer → PostgreSQL
                                                                      ↓
                                                              Alert Dispatcher → Webhook / Email
                                                                      ↓
                                                              Dashboard (WebSocket)
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **Kafka** as backbone | Decouples ingestion from scoring, enables replay, supports horizontal scaling |
| **Redis sorted sets** for features | O(log N) sliding-window queries without external schedulers |
| **Hybrid ML + Rules** | Rules catch known patterns (brute force, DDoS); ML catches novel anomalies |
| **EWMA IP Reputation** | Recent events weighted more; one false positive doesn't permanently stain an IP |
| **Model hot-swap** | Retrain replaces artifacts on disk; scorer reloads without restarting consumers |

## Tech Stack

- **Backend**: FastAPI (Python 3.11)
- **Streaming**: Apache Kafka (KRaft mode)
- **ML**: scikit-learn (Isolation Forest) + PyTorch (Autoencoder)
- **Storage**: PostgreSQL 16 + Redis 7
- **Dashboard**: Vanilla HTML/JS + Chart.js
- **Infra**: Docker Compose

## ML Detection — 3 Phases

| Phase | Model | How it works |
|---|---|---|
| 1 | **Isolation Forest** | Unsupervised anomaly scoring — isolates outliers in feature space |
| 2 | **Autoencoder** | Reconstruction error as anomaly signal — high error = unusual pattern |
| 3 | **Hybrid** | Deterministic rules (brute force, DDoS, suspicious paths) + weighted ML ensemble |

## Feature Engineering (12 features)

| Feature | Source |
|---|---|
| `ip_req_count_1m`, `ip_req_count_5m` | Redis sliding window |
| `ip_fail_count_1m`, `ip_fail_count_5m` | Failed requests (4xx/5xx) |
| `unique_paths_1m` | Distinct paths accessed |
| `avg_status_code_1m` | Average HTTP status |
| `is_post`, `is_auth_endpoint` | Binary flags |
| `status_is_401/403/500` | Binary flags |
| `burst_rate` | Requests per second (5s window) |

## Quick Start

### 1. Start infrastructure

```bash
docker compose up -d
```

Wait for all services to be healthy:
```bash
docker compose ps
```

### 2. Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Train initial ML models

```bash
python -m app.ml.train
```

This generates synthetic training data and saves model artifacts to `app/ml/artifacts/`.

### 4. Start the API server

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Start the fake log generator

In a separate terminal:
```bash
python -m generator.fake_logs
```

### 6. Open the dashboard

Navigate to **http://localhost:8000/dashboard** — you'll see live events streaming in, anomaly scores, and alerts firing.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/events/` | Paginated event listing (filters: `source_ip`, `min_score`, `attack_type`) |
| `GET` | `/api/events/count` | Total event count |
| `GET` | `/api/events/{id}` | Single event detail |
| `PATCH` | `/api/events/{id}/label` | Label event for feedback loop |
| `GET` | `/api/alerts/` | Alert listing (filters: `severity`, `resolved`) |
| `GET` | `/api/alerts/stats` | Aggregate alert statistics |
| `POST` | `/api/alerts/{id}/resolve` | Resolve alert (mark false positive) |
| `GET` | `/api/reputation/{ip}` | IP reputation lookup |
| `PATCH` | `/api/reputation/{ip}/tag` | Manual IP tag override |
| `POST` | `/api/retrain/` | Trigger model retraining |
| `WS` | `/ws/live` | Live event stream (WebSocket) |

## Testing

```bash
pytest tests/ -v
```

## Project Structure

```
projectai/
├── docker-compose.yml       # Kafka, PostgreSQL, Redis
├── Dockerfile               # App container
├── requirements.txt
├── config/settings.py       # Pydantic env-driven config
├── app/
│   ├── main.py              # FastAPI app + lifespan
│   ├── api/                 # Route handlers
│   ├── models/              # ORM + Pydantic schemas
│   ├── services/            # Business logic
│   └── ml/                  # ML models + training
├── generator/fake_logs.py   # Fake traffic generator
├── dashboard/               # Live SPA dashboard
└── tests/                   # Unit + integration tests
```

## Elite Features

- **IP Reputation System** — EWMA-based scoring, auto-tagging (trusted/suspicious/blocked)
- **Attack Classification** — brute force, DDoS spike, suspicious API paths
- **Self-Learning Loop** — mark false positives → retrain models → hot-swap
- **Live Dashboard** — real-time event stream, alert feed, traffic charts via WebSockets

## ☁️ Deployment

### Option A: Free Tier (Lite Mode) — **Render**
The "Lite Mode" replaces Kafka with **Redis Pub/Sub** to fit within free hosting limits (512MB RAM).

[![Deploy to Render](https://render.com/images/deploy-to-render.svg)](https://render.com/deploy)

1. **Click the button above** (or upload to your GitHub and use the `render.yaml` blueprint).
2. Render will automatically provision:
   - **FastAPI App** (Web Service)
   - **Log Generator** (Background Worker)
   - **PostgreSQL** & **Redis** (Managed)
3. The system will automatically detect `MESSAGING_TYPE=redis` and start the Lite pipeline.

### Option B: Full Production — **Cloud VPS (DigitalOcean/AWS)**
Best for high-throughput environments where **Kafka** is required.

### 1. Prepare Server
```bash
# Install Docker & Docker Compose on your server
# Clone your repository
git clone <your-repo-url>
cd projectai
```

### 2. Configure Environment
```bash
cp .env.production .env
# Edit .env to change passwords/secrets if necessary
nano .env
```

### 3. Launch with Docker Compose
```bash
docker compose up --build -d
```

### 4. Initialize ML Models
Since the models need to be trained once to generate artifacts:
```bash
docker compose exec app python -m app.ml.train
```

Navigate to `http://<your-server-ip>:8000/dashboard` to see your live SOC in production!

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/events/` | Paginated event listing (filters: `source_ip`, `min_score`, `attack_type`) |
| `GET` | `/api/events/count` | Total event count |
| `GET` | `/api/events/{id}` | Single event detail |
| `PATCH` | `/api/events/{id}/label` | Label event for feedback loop |
| `GET` | `/api/alerts/` | Alert listing (filters: `severity`, `resolved`) |
| `GET` | `/api/alerts/stats` | Aggregate alert statistics |
| `POST` | `/api/alerts/{id}/resolve` | Resolve alert (mark false positive) |
| `GET` | `/api/reputation/{ip}` | IP reputation lookup |
| `PATCH` | `/api/reputation/{ip}/tag` | Manual IP tag override |
| `POST` | `/api/retrain/` | Trigger model retraining |
| `WS` | `/ws/live` | Live event stream (WebSocket) |

## Testing

```bash
pytest tests/ -v
```
