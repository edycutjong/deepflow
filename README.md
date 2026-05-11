# 🐋 Silent Whale

**DeFi Alpha Signal Scanner** — Autonomous scoring engine that monitors tokenless DeFi protocols for pre-TGE/airdrop signals using on-chain TVL data, VC funding intelligence, and GitHub commit analysis.

[![CI](https://github.com/edycuDev/DeepFlow/actions/workflows/ci.yml/badge.svg)](https://github.com/edycuDev/DeepFlow/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![SQLAlchemy 2.0](https://img.shields.io/badge/SQLAlchemy-2.0-orange)
![License](https://img.shields.io/badge/license-MIT-green)

---

## How It Works

Silent Whale runs a continuous **Scrape → Score → Alert** pipeline every 12 hours:

```
DefiLlama API ──→ Filter tokenless protocols ──→ Upsert to Postgres
                                                        │
GitHub Commits ──→ Keyword scan (tge, airdrop) ────────→│
                                                        │
VC Funding Data ──→ Tier-1/Tier-2 matching ────────────→│
                                                        ▼
                                              ┌─────────────────┐
                                              │  Scoring Engine  │
                                              │                  │
                                              │  TVL gradient    │
                                              │  Growth 30d %    │
                                              │  VC decay        │
                                              │  GitHub signals  │
                                              └────────┬────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │  Alert Router    │
                                              │                  │
                                              │  ≥75 → 🚨 NOW   │
                                              │  ≥50 → 👀 Watch  │
                                              │  Quiet hours     │
                                              │  Deduplication   │
                                              └────────┬────────┘
                                                       │
                                                       ▼
                                                  Telegram Bot
```

## Scoring Model

Each protocol is scored across four categories with **time-decay** applied to prevent stale signals from inflating scores:

| Category | Max Points | Decay Half-Life | Signal Source |
|----------|-----------|-----------------|---------------|
| **TVL** | 20 | None | DefiLlama `/protocols` |
| **TVL Growth (30d)** | 15 | None | Computed from `tvl_snapshots` |
| **VC Funding** | 25 | 180 days | Funding round data |
| **GitHub Signals** | 30 | 60–90 days | Commit keyword scanning |

**Total possible score: 90 points**

### VC Tier System

Funding scores use a lead/co-lead model with a `0.25x` co-lead multiplier:

- **Tier 1** (20 pts base): a16z, Paradigm, Polychain, Multicoin, Binance Labs, Framework, Variant, Hack VC, Placeholder
- **Tier 2** (10 pts base): Dragonfly, Coinbase Ventures, Spartan Group, Animoca, Delphi Digital

### Decay Function

All time-sensitive signals use exponential decay:

```
decayed_score = raw_score × 0.5^(days_old / half_life_days)
```

A funding round from Paradigm scored 180 days ago → `20 × 0.5 = 10 pts`

---

## Architecture

```
silent_whale/
├── app/
│   ├── alerts/
│   │   └── telegram.py          # Telegram bot with quiet hours + dedup
│   ├── core/
│   │   ├── config.py            # Pydantic Settings (env → DSN)
│   │   ├── config_loader.py     # Thread-safe YAML scoring config
│   │   ├── healthcheck.py       # HTTP /health endpoint for Docker
│   │   ├── logging.py           # Dual-mode logging (JSON/pretty)
│   │   ├── metrics_collector.py  # Async context manager with rollback
│   │   ├── outcomes.py          # Outcome tracking & backtesting
│   │   ├── scoring.py           # Multi-factor scoring engine
│   │   └── source_health.py     # Auto-disable after N failures
│   ├── db/
│   │   ├── models.py            # 9 SQLAlchemy 2.0 ORM tables
│   │   ├── metrics.py           # IngestionMetric model
│   │   └── session.py           # Async engine (pool_size=3)
│   ├── pipeline/
│   │   └── score_pipeline.py    # Scrape → Score → Alert orchestrator
│   ├── scrapers/
│   │   ├── defillama.py         # httpx + tenacity retry scraper
│   │   ├── github.py            # Commit keyword scanner
│   │   └── funding.py           # DefiLlama /raises ingestion
│   └── main.py                  # APScheduler + health server
├── alembic/                     # Database migrations
├── tests/                       # pytest + respx (8 test files)
├── scripts/
│   └── backup.sh                # Nightly pg_dump with 14-day rotation
├── config.yaml                  # Scoring weights & VC tier lists
├── docker-compose.yml           # Postgres 16 + app
├── Dockerfile                   # Multi-stage (libpq5 runtime)
└── .github/workflows/ci.yml    # Test → Deploy pipeline
```

### Database Schema

| Table | Purpose |
|-------|---------|
| `projects` | Core entity — slug, TVL, latest score |
| `tvl_snapshots` | Historical TVL for growth calculation |
| `funding_rounds` | VC investment records with round dates |
| `github_signals` | Keyword hits from commit scanning |
| `github_overrides` | Manual false positive flags |
| `source_health` | Scraper reliability tracking |
| `alert_queue` | Pending/sent Telegram alerts |
| `score_history` | Full scoring audit trail with breakdown |
| `project_outcomes` | Actual results for backtesting accuracy |
| `ingestion_metrics` | Scraper performance telemetry |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12 |
| ORM | SQLAlchemy 2.0 + asyncpg |
| Validation | Pydantic v2 + pydantic-settings |
| HTTP | httpx + tenacity (retry) |
| Scheduler | APScheduler 3.10.4 |
| Alerts | python-telegram-bot v20+ |
| Database | PostgreSQL 16 Alpine |
| Migrations | Alembic |
| Logging | Loguru |
| Container | Docker Compose |
| CI/CD | GitHub Actions → SSH deploy |
| Infrastructure | Hetzner Singapore VPS (4GB RAM) |

---

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- PostgreSQL 16 (or use the included Docker service)

### 1. Clone & Configure

```bash
git clone https://github.com/edycuDev/DeepFlow.git
cd DeepFlow
cp .env.example .env
# Edit .env with your credentials
```

### 2. Start Database

```bash
docker compose up -d postgres
```

### 3. Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Run Migrations

```bash
alembic upgrade head
```

### 5. Start the Scanner

```bash
python -m app.main
```

### Docker (Production)

```bash
docker compose up -d --build
```

---

## Configuration

All scoring parameters are in `config.yaml` — hot-reloadable without restart:

```yaml
scoring:
  tvl:
    min_m: 5          # $5M minimum to score
    max_m: 50         # $50M for max points
    max_points: 20
  funding:
    tier_1_base_pts: 20
    co_lead_multiplier: 0.25  # 2nd+ VC gets 25% weight
    decay_half_life_days: 180
  github:
    keyword_hits:
      tge:
        points: 25
        decay_half_life_days: 60
      airdrop:
        points: 15
        decay_half_life_days: 90

thresholds:
  immediate_alert: 75  # 🚨 Send NOW
  watchlist: 50         # 👀 Track
  alert_dedup_delta: 10 # Suppress if score change < 10

operational:
  timezone: Asia/Jakarta
  quiet_hours: ["23:00", "07:00"]
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_USER` | Database user | `whale` |
| `POSTGRES_PASSWORD` | Database password | — |
| `POSTGRES_DB` | Database name | `silent_whale` |
| `POSTGRES_HOST` | Database host | `localhost` |
| `POSTGRES_PORT` | Database port | `5432` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token | — |
| `TELEGRAM_CHAT_ID` | Telegram chat/channel ID | — |

---

## Testing

```bash
pip install -r requirements-test.txt
pytest tests/ -v
```

### Test Coverage

| Module | Tests | Key Validations |
|--------|-------|-----------------|
| `test_config_loader` | 7 | YAML loading, validation, hot-reload safety |
| `test_ingestion` | 10 | Protocol filtering (6 edges), retry recovery, crash rollback |
| `test_scoring` | 7 | Gradient, decay, VC sorting, category capping |
| `test_telegram` | 7 | Quiet hours, dedup, threshold routing |

### Linting

```bash
ruff check .
mypy app/ --ignore-missing-imports
```

---

## Deployment

### GitHub Actions CI/CD

The pipeline runs on every push:

1. **Test** — `pytest` against a service container Postgres
2. **Lint** — `ruff check` + `mypy`
3. **Deploy** — SSH into VPS, `git pull`, `docker compose up -d` (main branch only)

### VPS Setup

```bash
# On Hetzner Singapore VPS
mkdir -p /home/whale/silent_whale
cd /home/whale/silent_whale
git clone <repo> .
cp .env.example .env
# Configure .env
docker compose up -d

# Cron for nightly backups
chmod +x scripts/backup.sh
echo "0 3 * * * /home/whale/silent_whale/scripts/backup.sh" | crontab -
```

### Backup & Recovery

- **Nightly** compressed `pg_dump` via `scripts/backup.sh`
- **14-day retention** with automatic pruning
- Connects directly to `localhost:5432` (bypasses `docker exec`)

---

## Scheduler Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `full_cycle` | Every 12h | Scrape → Score → Alert pipeline |
| `alert_flush` | Every 1h | Drain alerts queued during quiet hours |
| `health_digest` | Daily 09:00 | Source health summary via Telegram |

---

## Source Health Monitoring

- Tracks consecutive failures per scraper source
- Auto-disables after 5 consecutive failures with Telegram notification
- Disabled sources are skipped in the full cycle
- Manual re-enable via `re_enable_source(session, "source_name")`
- Daily health digest sent at 09:00

## Outcome Tracking

Record actual project outcomes for model accuracy backtesting:

```python
from app.core.outcomes import record_outcome, get_accuracy_report

await record_outcome(session, "aave", "tge_launched", notes="Token launched")
await record_outcome(session, "rug-project", "rug")

report = await get_accuracy_report(session)
# {"hit_rate": 75.0, "false_positive_rate": 10.0, ...}
```

Valid outcome types: `tge_launched`, `airdrop_confirmed`, `airdrop_rumor`, `rug`, `abandoned`, `still_building`

---

## Roadmap

- [x] ~~GitHub commit keyword scraper~~
- [x] ~~VC funding round scraper~~
- [x] ~~Source health auto-disable~~
- [x] ~~Outcome tracking & backtesting~~
- [x] ~~Structured JSON logging~~
- [x] ~~Docker healthcheck~~
- [ ] Web dashboard for score visualization
- [ ] Multi-chain TVL aggregation
- [ ] Webhook support (Discord, Slack)

---

## License

MIT
