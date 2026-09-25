# Render deployment

FOBOS deploys as a Django API plus PostgreSQL on Render, with the React POS
hosted separately on Vercel. The backend `render.yaml` creates the uniquely
named `fobos-commerce-ledger-api` and database so it cannot update an unrelated
service already using the older `fobos-api` hostname.

## Backend

The backend Blueprint creates PostgreSQL and a persistent media disk for
generated barcode images. It runs migrations and `collectstatic` before starting
Gunicorn. The `/health/` check verifies both Django and its database. The API
hostname is assigned by Render; use that exact URL as the frontend API base.
Render's forwarded HTTPS header is trusted so generated absolute media URLs use
HTTPS on phones and other secure clients.

The Blueprint keeps demo and live payment adapters disabled by default. Before
enabling real transactions, review provider readiness, then set
`FOBOS_USE_LIVE_ADAPTERS=true` and configure provider secrets in the API service.
The Blueprint prompts for SMTP credentials so signup verification emails can be
delivered. Provider keys belong only in the API service, never the frontend.

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
