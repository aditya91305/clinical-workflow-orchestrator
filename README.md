# Enterprise Clinical Trial Data Ingestion & Orchestration System

An asynchronous, fault-tolerant clinical data ingestion engine and telemetry dashboard built with **n8n**, **Flask**, **SQLAlchemy**, and **PostgreSQL**. 

The system enforces strict medical identifier validation, schema normalization, idempotent record upserts, and visual execution tracing to prevent clinical record corruption.

---

## System Architecture

```text
[ External Clinical EMR / Webhook Trigger ]
                    │
                    ▼ (HTTP POST)
┌─────────────────────────────────────────────────────────────┐
│ 1. INTAKE & NORMALIZATION (n8n Workflow Engine)             │
│  - Captures unstructured/cased input payloads               │
│  - Trims whitespace & maps legacy schemas (notes → findings)│
│  - Enforces execution-level error branching                 │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP POST (:5000)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. VALIDATION & BUSINESS GOVERNANCE (Flask API Gateway)     │
│  - Strict regex boundary checks: PT-\d{4,6}, CT-\d{4}-[A-Z] │
│  - Field bounds and clinical status verification            │
│  - Idempotent upsert logic (prevents duplicate patients)    │
│  - Atomic database transactions with rollback protection    │
└──────────────┬──────────────────────────────┬───────────────┘
               │ HTTP 200/201                 │ HTTP 422/500
               ▼                              ▼
┌──────────────────────────────┐ ┌────────────────────────────┐
│ 3. PERSISTENCE (PostgreSQL)  │ │ 4. AUDIT / DEAD-LETTER LOG │
│  - Table: clinical_reports   │ │  - Diverts failed records  │
│  - B-Tree index on IDs       │ │  - Maintains trace audit   │
│  - ACID compliant storage    │ └────────────────────────────┘
└──────────────┬───────────────┘
               │ GET /api/reports
               ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. TELEMETRY & MONITORING DASHBOARD (HTML5 / Vanilla JS)    │
│  - Real-time KPI cards & verified database activity feed    │
│  - Integrated reverse proxy (/api/simulate-ingest)          │
│  - Warm, minimal UI aesthetic                               │
└─────────────────────────────────────────────────────────────┘
