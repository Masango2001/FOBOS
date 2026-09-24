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

## 5. Contrat caissier Frontend — 4 points reçus et traités

Le Frontend a soumis un contrat caissier (workflow Lumicash-OTP). Points et
décisions :

### 5.1 Chemin du checkout

- **Contrat front** : `POST /cart/checkout`.
- **Décision** : conforme à la Spec §4 et à l'implémentation existante
  (`sales/urls.py`). **Aucun changement** : la réponse est celle du §5.2.

### 5.2 `order_id` — généré serveur, retourné par le checkout

- **Contrat** : le body du checkout `{ lines:[{product_id, qty}] | amount }`
  ne contient **pas** d'`order_id` ; la réponse le renvoie.
- **Décision** : c'est déjà le cas. `order_id` est généré serveur (uuid4 hex,
  `payments/services.py`) et sert de clé d'**idempotence** de la confirmation
  (PRD §32) : le front réutilise l'`order_id` retourné pour le polling
  (`GET /payments/:id/status`) et pour `payments/onramp/confirm`.

### 5.3 Nouveaux endpoints onramp OTP (Lumicash)

- **Contrat / Spec §4** : `POST /payments/onramp/request-otp
  { customer_phone, amount }` puis `POST /payments/onramp/confirm
  { customer_phone, amount, otp, order_id }`.
- **État initial** : **manquants** dans le backend.
- **Décision / implémentation** : ajoutés :
  - `POST /payments/onramp/request-otp` → 200 `{ status: "otp_sent" }`
    (+ `demo_otp` en mode démo uniquement) ; 503 `adapter_not_installed`
    si le vrai adapter BitLibera (Backend Dev B) n'est pas enregistré.
  - `POST /payments/onramp/confirm` → valide l'OTP puis confirme le paiement
    (`confirm_payment`, idempotent sur `order_id`) ; réponses :
    - 200 = PaymentSerializer (Shape §5.4) ;
    - 404 si l'`order_id` est inconnu du business ;
    - 400 `invalid_otp` si l'OTP est invalide/consommé ;
    - 503 si l'adapter onramp n'est pas installé ;
    - un retry après succès renvoie 200 (déjà confirmé) sans réevaluer l'OTP —
      idempotence sans double écriture ledger.
- Contrainte d'implémentation : uniquement via l'interface `OnrampAdapter`
  (`payments/adapters.py`) — le vrai relais BitLibera doit se brancher sans
  toucher au code métier (`payments/demo.py` = stand-in local).

### 5.4 Formes de réponse + statuts

- **Formes contractuelles** : CheckoutResponse `{ payment_request, order_id,
  amount_bif, amount_sats?, status, receipt }` ; PaymentStatusResponse
  `{ order_id, payment_request?, amount_bif?, amount_sats?, lumicash_phone?
  , status, confirmed_at?, receipt? }`.
- **Enum de statuts** : `pending | confirmed | failed | expired`.
- **Décision / implémentation** :
  - le checkout et `payments/<id>/status` renvoient la forme contractuelle
    (`PaymentSerializer`, `payments/serializers.py`) ;
  - `expired` ajouté au modèle (`Status.EXPIRED`) : le status view le déduit
    quand l'adapter rapporte « expired » — aucune écriture financière.
    La confirmation reste déclenchée par `confirm_payment` (idempotent) ;
  - `receipt` : `{ id, content, created_at }` du reçu de la vente, `null`
    tant que le paiement n'est pas confirmé ;
  - `lumicash_phone` : présent dès qu'un onramp a été utilisé pour le paiement.

## 6. UUID partout + barcode produit auto-généré

Décision d'architecture validée avec le Frontend/owner :

### 6.1 Clés primaires UUID

- **Toutes les tables** passent en `UUIDField(primary_key=True, default=uuid4)`
  (`accounts`, `products`, `payments`, `sales`, `ledger`, `automation` —
  y compris Business et User). Migrations régénérées, base récréée, comptes
  demo `alice@`/`bob@fobos.test` re-créés.
- **Impact API** :
  - `product_id` dans `POST /cart/checkout` est désormais un **UUID string** ;
  - `GET /payments/<uuid:pk>/status` (route `uuid`);
  - tous les ïds retournés par les endpoints sont des UUID strings ;
  - JWT : claim `business_id` = UUID string.
- La contrainte d'unicité `uniq_business_barcode` est inchangée (UUID ⇒
  collision impossible entre barcodes auto-générés).

### 6.2 Barcode FOBOS auto-généré (content : nom, prix, id)

- **Règle** : un produit créé **sans** barcode fabricant reçoit un barcode
  FOBOS automatiquement — il encode `name | unit_price | product_id`
  (`products/services.py`, encodage `F.` + base64url JSON). Autonomie du caissier :
  le scanner décode le code pour retrouver le produit par son id sans table de
  correspondance.
- `GET /products/scan/:barcode` : résout d'abord le payload FOBOS par `id`,
  sinon correspondance exacte sur le barcode fabricant (ex. EAN numérique) —
  rétro-compatible.
- `barcode` passe à `max_length=128` (le code généré fait < 120 caractères).
- **Image du barcode** : `GET /products/<uuid:pk>/barcode` renvoie une image
  PNG scannable (Code128, `python-barcode` + `Pillow`, `products/services.py`)
  — lisible/affichable par le front sans lib client. Cache
  `public, max-age=31536000, immutable` (le code est stable). Owner et caissier
  y ont accès ; 404 si produit inconnu/autre business/sans barcode, 422 si
  barcode non-ASCII.

### 6.3 Cohérences gardées

- Snapshots de panier (`Payment.lines`), reçus (`Receipt.content`) et résultat
  d'automation stockent les ids en **string UUID** ; `sales/services.py` et
  `payments/services.py` les re-parse en `uuid.UUID` pour la résolution.
- Token de vérification d'email : signe l'UUID string (invariant inchangé pour
  le front).