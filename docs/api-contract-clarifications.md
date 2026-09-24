# Clarifications du contrat API — MVP Commerce & Ledger

Document de décision côté Backend Dev A. Chaque point liste l'écart signalé entre
le contrat (Tech Spec §4 / AGENTS.md) et l'implémentation, puis la décision retenue.

## 1. `PUT /products/:id` (édition de produit)

- **Signalé** : un endpoint `PUT /products/:id` serait nécessaire pour l'édition,
  alors que le contrat §4 ne définit que `POST /products` + `GET /products`.
- **État réel** : **non implémenté côté backend** (`products/urls.py` expose
  uniquement `products`, `products/scan/<barcode>`, `inventory`).
- **Décision** : conforme au contrat §4 — **aucun** `PUT /products/:id` au MVP.
  `POST /products` (owner uniquement, barcode unique par business) couvre la
  création ; la mise à jour de produits est **hors périmètre** et à réévaluer
  si le Frontend en a besoin (ex. correction stock/déstockage → `PATCH`).

## 2. Formes exactes de `/dashboard`, `/ledger`, `/inventory`, `/automations`

- **Signalé** : les docs §4 ne décrivent que le *concept* de chaque écran owner ;
  les types de réponse actuels seraient des propositions, pas le contrat.
- **Décision** : l'implémentation est **alignée sur le concept** et les données
  sont réellement calculées (revenue/cogs/marge sur les FinancialEvents,
  ledger = les entrées REVENUE/COGS, inventory = stock + valeurs + low_stock,
  automations = règles + executions). Les formes actuelles sont la **valeur de
  référence** du contrat backend pour le Frontend tant que §4 ne précise pas
  autre chose. Toute évolution contractuelle se fait via une PR sur ce repo.

## 3. `createAutomation` envoie `active`

- **Signalé** : AGENTS.md liste `active` dans l'entité Automation mais la ligne
  API §4 est `{ trigger, condition, action }`.
- **Décision** : `active` est **accepté et requis** (booléen, `true` par défaut
  côté modèle, `automation/models.py:21`) — le modèle et le serializer
  `automation/serializers.py:9` l'exposent. C'est une **extension confirmée**
  de la ligne §4, cohérente avec AGENTS.md : une règle créée éteinte
  (`active: false`) n'est pas évaluée à la confirmation de vente.

## 4. Création d'un caissier — c'est l'owner qui le crée

- **Point de conception** : le signup ne crée que l'owner (`SignupSerializer`).
  Qui crée les comptes caissier ?
- **Décision / implémentation** : **l'owner** crée ses caissiers via un nouvel
  endpoint — **`POST /auth/cashiers`** (owner uniquement, 403 pour un caissier,
  401 non authentifié) :

  ```json
  { "name": "Bob", "email": "bob@...", "phone": "+2577...", "password": "..." }
  ```

  Comportement :
  - rôle `cashier`, rattaché au business de l'owner appelant, `email_verified=false` ;
  - **email de vérification envoyé** (même flux signé/expirant que le signup) —
    le caissier ne peut se connecter qu'**après avoir vérifié son email** (géré
    par le login JWT existant) ;
  - email dupliqué → 400 « already registered ».
- Cet endpoint est une **extension au-delà du contrat §4** (la gestion
  d'équipe n'y figure pas), décidée pour permettre un vrai mode caissier
  multipliée sans passer par l'admin/shell.