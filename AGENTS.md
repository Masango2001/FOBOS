# Repository Guidelines

## Project Structure & Module Organization

FOBOS is a Python 3.12 / Django REST Framework backend. `config/` contains project settings, URL routing, and WSGI/ASGI entry points. Feature apps are organized by domain: `accounts/`, `products/`, `sales/`, `payments/`, `ledger/`, and `automation/`; each owns its models, serializers, views, migrations, and tests. The generated OpenAPI contract is `schema.yaml`. Docker setup is in `Dockerfile` and `docker-compose.yml`; environment variable names are listed in `.env.example`.

## Build, Test, and Development Commands

Use Docker Compose for app and database commands; host Python/PostgreSQL installs are not required.

```bash
sh scripts/bootstrap-ci-env.sh
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py spectacular --file schema.yaml --validate --fail-on-warn
docker compose run --rm web pytest
```

The schema command regenerates and validates the committed API contract. Pytest enforces the 80% coverage threshold. Run quality checks with `docker compose run --rm web ruff check .`, `ruff format --check .`, `mypy .`, `bandit -c pyproject.toml -r .`, and `pip-audit -r requirements/dev.txt` (prefix each with the Compose command).

## Coding Style & Naming Conventions

Use four spaces, double quotes, and Ruff’s 100-character line limit. Use `snake_case` for modules, functions, and fields; `PascalCase` for classes; and `test_*.py` / `test_*` for tests. Keep business logic in domain services, input/output shapes in serializers, and database changes in app migrations. Treat documented API field names as compatibility contracts; do not rename them without an agreed migration plan.

## Testing Guidelines

Tests use pytest and pytest-django. Add or update tests in the owning app, typically `accounts/tests.py` or `products/openapi_tests.py`. Schema changes must pass OpenAPI validation with `--fail-on-warn`; run the full pytest suite to verify behavior and coverage.

## Commit & Pull Request Guidelines

Recent commits use concise imperative subjects, often with a scope prefix such as `feat(products): ...`, `refactor(env): ...`, or `docs(openapi): ...`. Work on a dedicated branch and open a PR to `develop`. Describe behavior and contract changes, link relevant issues when available, and wait for the required CI checks (Docker build, tests, Ruff, mypy, Bandit, pip-audit, and Trivy) before merging. Promote approved changes from `develop` to `main` through a PR.

## Security & Configuration Tips

Copy `.env.example` or run the bootstrap script to create local configuration. Keep `.env.dev`, `.env.prod`, passwords, and Django secret keys out of Git. Settings fail fast when required secrets or database values are missing; do not add hard-coded fallbacks.
