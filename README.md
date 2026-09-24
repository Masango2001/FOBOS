# FOBOS — Backend Commerce & Ledger

Backend core de la Plateforme d'Opérations Financières (MVP Hackathon) : data model,
auth, produits/inventaire, transaction checkout→ledger, calculs financiers et moteur
d'automatisation. Développé **entièrement via Docker** — aucun environnement local Python
ni PostgreSQL nécessaire.

## Stack

- Python 3.12 · Django 5.2 LTS · Django REST Framework · PostgreSQL 17
- Linters : Ruff · mypy · Bandit
- Tests : pytest + pytest-cov · SCA deps : pip-audit · Trivy (image) · SonarCloud

## Démarrage rapide

**Prérequis :** Docker (Desktop/Engine + Compose v2). Aucune autre installation.

```bash
cp .env.example .env          # premières valeurs de dev correctes

docker compose build          # build de l'image web (jamais poussée vers un registry)
docker compose up             # web sur http://localhost:8000 + db PostgreSQL
```

Dans un second terminal :

```bash
docker compose exec web python manage.py migrate          # appliquer les migrations
docker compose exec web python manage.py createsuperuser  # admin Django (optionnel)
docker compose run --rm web python manage.py makemigrations   # nouvelles migrations
```

## Commandes de tests / qualité (toutes via Docker)

```bash
docker compose run --rm web pytest                                   # tests + coverage (seuil 80% dans pyproject.toml)
docker compose run --rm web ruff check .                             # lint
docker compose run --rm web ruff format --check .                    # format
docker compose run --rm web mypy .                                   # types
docker compose run --rm web bandit -c pyproject.toml -r .            # sécurité statique
docker compose run --rm web pip-audit -r requirements/dev.txt        # vulnérabilités deps
```

## Pre-commit (hôte uniquement)

`pre-commit` est un outil **git : il tourne côté hôte, pas dans Docker**. C'est la seule
exception à la règle "tout via Docker". Installation :

```bash
pip install pre-commit   # ou : pipx install pre-commit
pre-commit install       # enracine les hooks dans .git
pre-commit run --all-files
```

Hooks configurés : ruff (lint + format), mypy, `trailing-whitespace`, `end-of-file-fixer`,
`check-yaml`, `check-added-large-files`.

## Vérification d'email (lien signé)

- `POST /auth/signup` — crée `Business` + `User` (email = identifiant), envoie un email
  avec un bouton de vérification. **Le lien signé (24 h, `TimestampSigner`) n'apparaît
  que dans le `href` du bouton**, jamais en texte clair.
- `GET /auth/verify-email/<token>/` — valide le token, marque `email_verified`.
- `POST /auth/resend-verification` `{ email }` — renvoie un lien si le précédent a expiré.
- `POST /auth/login` — **refusé tant que l'email n'est pas vérifié** ; le JWT porte le
  claim `role` (`owner`/`cashier`) et `business_id`.

En dev, l'email « part » dans la console du serveur (backend console). Pour l'envoi réel,
renseignez `EMAIL_BACKEND`/`EMAIL_HOST_*` dans `.env`.

## CI (GitHub Actions)

Workflow `.github/workflows/ci.yml`, déclenché sur chaque **PR vers `develop`**. Chaque
outil est un job séparé (build Docker, ruff, mypy, bandit, pip-audit, trivy, pytest +
coverage, sonar). Aucun `docker push` ni `docker/login-action` : l'image n'est **jamais**
publiée dans un registry, elle est buildée localement par la CI pour valider le build.

**Pour bloquer le merge sur `develop` :** activer manuellement dans GitHub → Settings →
Branches → branch protection sur `develop` → « Require status checks to pass before
merging » et cocher les checks du workflow.

**SonarCloud :** le job `sonar` est inactif tant que le secret `SONAR_TOKEN`
(et `SONAR_HOST_URL`) n'est pas défini dans les secrets du repo Actions — il ne bloque
donc pas la CI en attendant. Le rapport de couverture `coverage.xml` est généré par
pytest puis transmis à Sonar.

## Éditeur (VS Code)

Le projet est entièrement typé (mypy en CI, `django-stubs`). Avec l'extension **Pylance**
(ou base Python) dans VS Code, vous obtenez auto-complétion et vérification en temps réel
sans rien installer de plus — cohérent avec la config `[tool.mypy]` de `pyproject.toml`.
Pylance est un outil d'éditeur, il ne fait **pas** partie de la CI.

## Repo & conventions

- GitHub : chacun travaille sur sa branche, ouvre une PR vers `develop`. Les rewrites
  doivent passer la CI (required status checks).
- Les noms de champs du contrat (Tech Spec §2 : `settlement_preference`, `stock_qty`,
  ...) ne doivent jamais être renommés : les frontends et Backend Dev B s'appuient dessus.