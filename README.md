# CURSORAGRI

This project is a Django-based agricultural risk monitoring and forecasting application.

## Project layout

```text
.
├── agri_dashboard/        # Django project configuration and settings
├── dashboard/             # Main application logic, models, services, views
├── data/                  # Climate, seasonal, and source data assets
├── database/              # SQL schema definitions and database-related files
├── docs/                  # Project documentation and technical guides
├── scripts/               # Utility scripts grouped by purpose
│   ├── automation/        # Startup and automation helpers
│   ├── etl/               # ETL / data preparation scripts
│   ├── reports/           # Reporting and PDF generation scripts
│   ├── validation/        # Data quality and system validation checks
│   └── ...
├── tests/                 # Automated test files
├── templates/             # Django HTML templates
├── static/                # Static frontend assets
├── config/                # Runtime configuration files (Postgres, PgBouncer)
├── artifacts/             # Generated outputs (plots, reports, model artifacts)
├── backups/               # Backup files and historical snapshots
├── keys/                  # Service credentials / access files
├── locale/                # Translation files
├── logs/                  # Runtime and application logs
├── models/                # Model metadata / training artifacts
├── manage.py              # Django management entry point
├── requirements.txt       # Python dependencies
├── Dockerfile             # Container definition
├── .env                   # Local environment configuration
├── .env.example           # Template for environment configuration
├── .gitignore             # Git ignore rules
├── QUICKSTART.md          # Quick-start guide
├── QUICK_START_AUTOMATION.md
├── AUTOMATION_SETUP.md
└── render.yaml            # Deployment config
```

## Guidelines

- Keep application code under `agri_dashboard/` and `dashboard/`.
- Put ad hoc or one-off operational scripts under `scripts/` by purpose.
- Keep generated outputs in `artifacts/`, `logs/`, or `backups/` instead of the repo root.
- Keep database schema and migration-related SQL in `database/`.
- Keep deployment and infrastructure config in `config/`.

## Common commands

```bash
python manage.py migrate
python manage.py runserver
python manage.py collectstatic
```
