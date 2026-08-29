# Forex SaaS Platform

This repository is being evolved from a single-user forex bot into a demo-first
web platform. During the first stage it will use the owner's details and the
owner's IG demo account only. Multi-tenant operation, subscriptions, third-party
accounts, and live trading are explicitly deferred until legal, regulatory,
security, and broker approval work has been completed.

## Repository layout

```text
apps/
  web/                    Angular application (created with Angular CLI)
services/
  platform-api/           FastAPI HTTP API, authentication and application logic
  trading-engine/         Signals, risk, orders and broker adapters
packages/
  contracts/              Shared API schemas and generated clients
database/
  scripts/                SQL Server provisioning and migration scripts
docs/                      Architecture, decisions and implementation plan
infrastructure/            Local/server deployment configuration
tests/
  integration/            Cross-service and database tests
ig-ai-forex-bot/           Existing prototype retained as a legacy reference
```

Do not copy secrets, `.env` files, SQLite databases, logs, reports, or trained
model files out of the legacy project. Code is migrated deliberately, one
component at a time, with tests.

## Start here

1. Review [docs/IMPLEMENTATION-PLAN.md](docs/IMPLEMENTATION-PLAN.md).
2. Review [docs/OPERATIONS.md](docs/OPERATIONS.md) for the automatic services,
   backup/restore checks and incident controls.
3. Ask the SQL Server administrator to customise and run
   [database/scripts/001_create_database_and_login.sql](database/scripts/001_create_database_and_login.sql).
4. Create the Angular 21 workspace using the pinned command in the implementation
   plan. Do not scaffold it with `@angular/cli@latest`.
5. Scaffold the FastAPI service after the database connection details have been
   placed in a local, untracked environment file.

No live-trading path should be enabled during this implementation stage.
