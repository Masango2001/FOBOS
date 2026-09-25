# Render deployment

FOBOS deploys as a Django API plus PostgreSQL on Render, with the React POS
hosted separately on Vercel. The backend `render.yaml` creates the uniquely
named `fobos-commerce-ledger-api` and database so it cannot update an unrelated
service already using the older `fobos-api` hostname.

## Backend

The current Blueprint is a temporary free staging setup. It creates a free
PostgreSQL database and a free web service. Free Postgres expires 30 days after
creation, and free web services spin down after 15 minutes of inactivity. The
start command runs migrations and `collectstatic` before Gunicorn. Free services
cannot send SMTP on port 587, so verification messages are written to service
logs for staging; configure a supported email provider before production. There
is no persistent media disk, so backend-generated PNGs can disappear after a
restart; the frontend generates its barcode labels locally. Upgrade the API,
database, and media storage before using this as a durable production service.
The `/health/` check verifies both Django and its database. The API hostname is
assigned by Render; use that exact URL as the frontend API base. Render's
forwarded HTTPS header is trusted so absolute media URLs use HTTPS on phones.

The Blueprint keeps demo and live payment adapters disabled by default. Before
enabling real transactions, review provider readiness, then set
`FOBOS_USE_LIVE_ADAPTERS=true` and configure provider secrets in the API service.
Provider keys belong only in the API service, never the frontend.

## Frontend

The Vercel project builds the Vite app with `VITE_DEMO_MODE=false` and
`VITE_API_BASE_URL` set to the Render API URL. After creating the API service,
set this value in Vercel for Production and Preview, then redeploy. The backend
Blueprint allows the production frontend origin in `CORS_ALLOWED_ORIGINS`.

## OpenAPI contract

After backend migrations and view/serializer changes, regenerate the committed
contract from the running Compose service:

```bash
docker compose exec web python manage.py spectacular --file schema.yaml
```

The live schema and Swagger UI are available at `/api/schema/` and `/api/docs/`.
