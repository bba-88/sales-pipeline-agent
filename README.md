# Sales Outreach & Pipeline Agent

Autonomous AI-powered revenue generation platform. Built from the [Sales_Agent_Upperfunnel.md](../Sales_Agent_Upperfunnel.md) product spec.

## What It Does

- **Prospect Research Agent** — Enriches contacts with funding stage, tech stack, pain signals, and 3–5 personalization hooks using Claude
- **Message Generation Agent** — Writes hyper-personalized 5-step multi-channel outreach sequences
- **Response Handling Agent** — Classifies inbound replies (Interested / Not Now / Objection / etc.) and drafts AI responses
- **Orchestrator** — State machine managing the full lifecycle: New → Researching → Sequencing → Responded → Meeting Booked

## Quick Start

### 1. Install dependencies

```bash
cd sales-pipeline-agent
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 3. Run the server

```bash
uvicorn main:app --reload --port 8000
```

### 4. Open the dashboard

Navigate to **http://localhost:8000** in your browser.

## API Docs

FastAPI auto-generates interactive docs at **http://localhost:8000/docs**

## Usage Walkthrough

1. **Create a Campaign** — Define your ICP, value prop, and tone
2. **Add Prospects** — Enter contact info manually (CSV import coming soon)
3. **Enroll with AI ⚡** — Kicks off the research + sequence generation pipeline
4. **View Results** — See personalization hooks, fit score, and full outreach sequence
5. **Submit Replies** — Use the Reply Inbox to simulate/classify inbound replies

## Architecture

```
FastAPI (main.py)
├── /api/campaigns    — Campaign CRUD
├── /api/prospects    — Prospect management + enrollment
├── /api/analytics    — Dashboard metrics
│
Agents (agents/)
├── orchestrator.py      — State machine coordinator
├── prospect_research.py — Enrichment + personalization hooks
├── message_generation.py — Sequence writing
└── response_handler.py  — Reply classification + draft generation
│
Database (SQLite via SQLAlchemy async)
└── models.py — Prospect, Campaign, Sequence, Reply, Meeting, AuditLog
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Claude claude-sonnet-4-5 + claude-haiku-4-5 |
| Backend | Python 3.12, FastAPI, SQLAlchemy async |
| Database | SQLite (prototype) → PostgreSQL (production) |
| Frontend | Vanilla JS + Tailwind CSS |
| Agent SDK | Anthropic Python SDK |

## Roadmap to Production

- [ ] PostgreSQL + Redis (replace SQLite)
- [ ] Celery worker for background jobs
- [ ] Real LinkedIn automation (Playwright)
- [ ] SendGrid email sending
- [ ] Calendly meeting booking integration
- [ ] CRM sync (HubSpot, Salesforce)
- [ ] CSV bulk prospect import
- [ ] Multi-tenant auth (Auth0)
- [ ] Stripe billing
