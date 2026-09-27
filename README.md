# NexaFreight — Autonomous Multimodal Logistics & Maritime Intelligence Control Tower

[![CI](https://github.com/rajmontana/NexaFreight/actions/workflows/ci.yml/badge.svg)](https://github.com/rajmontana/NexaFreight/actions/workflows/ci.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16.2-black.svg?logo=next.js&logoColor=white)](https://nextjs.org)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

NexaFreight is an enterprise-grade autonomous multimodal logistics control tower and maritime intelligence platform. It provides end-to-end visibility across ocean freight, air cargo, road haulage, and warehouse hubs with real-time AIS vessel telemetry, predictive machine learning delay models, automated disruption mitigation, and an AI Operations Copilot powered by Google Gemini.

---

## Architecture Overview

NexaFreight runs as a coordinated two-tier architecture:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Next.js Frontend (Port 3000)                      │
│   • Interactive 3D Tactical Globe & Multimodal Corridor Map             │
│   • Operations Intelligence, Disruption Alerts & Financial Analytics    │
│   • AI Operations Copilot (Gemini & Rule-Based Intent Routing)          │
│   • Real-Time Position Stream Consumer (Server-Sent Events)             │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ REST & SSE (:8000)
┌────────────────────────────────────▼────────────────────────────────────┐
│                       FastAPI Backend (Port 8000)                       │
│   • Telemetry Engine: AISStream live WebSocket & High-Res Interpolation │
│   • Multimodal Router: Sea corridors (searoute), Road (ORS/OSRM), Air   │
│   • Disruption & Reroute Engine: 3 deterministic mitigation options     │
│   • SLA & Demurrage Monitor: Risk band calculations & auto-escalation   │
│   • Predictive ML: LightGBM delay classifier, StatsForecast demand     │
│   • Database: SQLite (local) / PostgreSQL with Async SQLAlchemy         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Key Capabilities

### 1. Global Multimodal Visibility & Real-Time AIS Telemetry
- **Live Vessel Tracking**: Integrates with live AIS feeds (`aisstream.io`) and high-frequency historical position interpolators.
- **Intermodal Corridor Engine**: Automatically computes and renders multi-leg journeys across ocean container shipping, air freight, and inland trucking routes.
- **Hub & Depot Infrastructure**: Live visualization of maritime ports, air hubs, and regional distribution warehouses.

### 2. Autonomous Disruption & Deterministic Rerouting
- **Automated Disruption Detection**: Real-time detection of canal blockages, severe weather, port labor delays, and terminal congestion.
- **Three-Way Recovery Generator**:
  1. **Accept Delay**: Evaluates cost and SLA impact of waiting out the disruption.
  2. **Port Divert**: Computes alternative maritime routes and terminal bypasses with distance, CO2, and demurrage trade-offs.
  3. **Modal Shift**: Triggers emergency air or expedited road freight for high-priority shipments near SLA breach thresholds.

### 3. Predictive Analytics & Operational Finance
- **Machine Learning Delay Classifier**: Pre-trained LightGBM model assessing delay risk based on shipment mode, route geography, and seasonal congestion.
- **Financial Risk Modeling**: Real-time calculations of demurrage penalties, inventory holding costs, and fuel surcharges.
- **Carbon Accounting**: GLEC-compliant CO2 emission calculations across all transportation modes.

### 4. NexaFreight AI Copilot
- **Intelligent Dispatch**: Hybrid query router using deterministic operational rules for high-precision entity lookups (vessels, shipments, alerts) and Google Gemini LLMs for complex advisory and root-cause analysis.
- **Auditable Provenance**: Every AI answer and metric carries explicit provenance badges (`REAL`, `DERIVED`, `REPLAYED`) ensuring full auditability.

---

## Directory Structure

```
.
├── backend/
│   ├── migrations/             # Alembic database migration scripts
│   ├── models/                 # Pre-trained ML models (LightGBM, StatsForecast)
│   ├── scripts/                # Database seed scripts & ingestion pipelines
│   ├── src/nexafreight/        # Application source code
│   │   ├── api/                # API routers (shipments, alerts, telemetry, copilot, etc.)
│   │   ├── core/               # Configuration, security, and database engine
│   │   ├── models/             # SQLAlchemy ORM models & Pydantic schemas
│   │   ├── services/           # Routing, telemetry, SLA checker, ML, reroute engine
│   │   └── workers/            # Background cron jobs & AIS listener workers
│   ├── tests/                  # Unit and integration test suite (600+ tests)
│   ├── alembic.ini             # Alembic configuration
│   ├── pyproject.toml          # Python project specification & dependencies
│   └── requirements.txt        # Production pip requirements
│
├── frontend/
│   ├── public/                 # Static assets, icons, and audio alerts
│   ├── src/
│   │   ├── app/                # Next.js App Router pages and proxy API routes
│   │   ├── components/         # Tactical UI components (GlobeMap, Analytics, Copilot)
│   │   ├── hooks/              # Custom React hooks (SSE streams, audio, telemetry)
│   │   └── lib/                # API clients, geo utilities, and style tokens
│   ├── package.json            # Node.js dependencies and scripts
│   ├── tsconfig.json           # TypeScript configuration
│   └── vitest.config.ts        # Frontend test configuration
│
├── .github/workflows/          # CI/CD automation (Pytest, Vitest, Typecheck, Build)
├── Makefile                    # Developer build and test shortcuts
└── README.md                   # Project documentation
```

---

## Quickstart Guide

### Prerequisites
- **Python**: 3.11 or newer
- **Node.js**: 20.x or newer, with `npm`
- **Git**

---

### 1. Backend Setup

```bash
# Navigate to the backend directory
cd backend

# Create and activate a Python virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

# Configure environment variables
cp .env.example .env
# Edit .env to set your JWT_SECRET and optional API keys (Gemini, AISStream, ORS)

# Apply database migrations
alembic upgrade head

# Seed initial operational data (users, shipments, telemetry, analytics)
python scripts/seed_user.py
python scripts/06_seed_analytics.py
python scripts/activate_and_seed_positions.py

# Start the FastAPI server
uvicorn nexafreight.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend API documentation (Swagger UI) is available at:
`http://localhost:8000/docs`

---

### 2. Frontend Setup

```bash
# Open a second terminal and navigate to the frontend directory
cd frontend

# Configure environment variables
cp .env.example .env.local
# Ensure NEXT_PUBLIC_NEXA_API_URL=http://localhost:8000

# Install Node dependencies
npm ci

# Start the Next.js development server
npm run dev
```

Open your browser at `http://localhost:3000`.

**Default Credentials:**
- **Email:** `operator@nexafreight.dev`
- **Password:** `changeme123`

---

## Testing & Quality Assurance

NexaFreight includes a comprehensive test suite across backend services and frontend components.

### Automated Test Suite
```bash
# Run both test suites via Makefile
make test

# Run backend tests (608 tests)
cd backend
pytest -q

# Run frontend unit tests (234 tests)
cd frontend
npx vitest run

# Run frontend typechecking
cd frontend
npx tsc --noEmit

# Test production build
cd frontend
npm run build
```

---

## API Reference Summary

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Authenticates user and returns JWT bearer token |
| `GET` | `/api/v1/shipments` | Lists multimodal shipments with filter by status/mode |
| `GET` | `/api/v1/shipments/{id}` | Detailed shipment manifest, leg geometries, and SLA |
| `GET` | `/api/v1/telemetry/stream` | Server-Sent Events (SSE) stream of live positions |
| `GET` | `/api/v1/alerts` | Active operational alerts and demurrage warnings |
| `POST` | `/api/v1/alerts/{id}/options` | Evaluates 3 reroute recovery options for an alert |
| `POST` | `/api/v1/decisions` | Commits an approved reroute decision to the audit log |
| `GET` | `/api/v1/analytics/summary` | Executive dashboard KPIs, volume, revenue, and CO2 |
| `POST` | `/api/v1/copilot/chat` | Interacts with the AI Copilot for operational queries |

## Infrastructure & Deployability

NexaFreight is designed to run locally using SQLite for rapid development, but is fully deployable to production infrastructure (e.g., Render, Oracle Cloud) using PostgreSQL and Docker.

### Local SQLite (Default)
By default, the backend uses an embedded SQLite database.
- Simply run `pip install -e .` and `alembic upgrade head`.
- The database is created locally at `backend/nexafreight.db`.

### Local Postgres via Docker Compose
For testing production parity locally, a `docker-compose.yml` is provided.
- Run `docker-compose up -d postgres` to spin up a local PostgreSQL 16 instance.
- The `docker-compose` setup includes the backend and frontend, but you can also run the database standalone.

### Environment Overrides (`DATABASE_URL`)
To connect the backend to a Postgres instance, set the `DATABASE_URL` environment variable:
```bash
export DATABASE_URL="postgresql+asyncpg://nexa:nexa_password@localhost:5432/nexafreight"
alembic upgrade head
uvicorn nexafreight.main:app
```
*Note: `DATABASE_URL` always takes precedence over the default SQLite database path.*

Stage A (Render): the repo root render.yaml declares the backend web
service from the GHCR image; deploy via Render Dashboard > New > Blueprint.

---

## Contributing (Windows note)

This repo is developed and verified via `git format-patch` / `git am --3way`
workflows. On Windows checkouts, set `git config core.autocrlf false` for
this repository to avoid phantom whole-file diffs; editors should save
UTF-8 without BOM. Console tooling assumes cp1252-safe (ASCII) output.

## License

This project is licensed under the MIT License — see the [LICENSE](frontend/LICENSE) file for details.
