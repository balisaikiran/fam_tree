# ICP Family Graph Service

FastAPI service exposing the family-tree graph (Neo4j) to the ICP dashboards
frontend. Designed to run alongside `bi-dashboards-service` in the same
Kubernetes cluster, sharing the same Keycloak realm and behind the same
ingress.

## What the frontend expects

The frontend (icp-dashboards-ui) sends requests to relative URLs. The ingress
must route these to this service:

```
POST /api/v1/family-tree/search
GET  /api/v1/persons/{spm_person_no}/exists
GET  /api/v1/persons/{spm_person_no}/tree
GET  /static/img/...                          # only if you serve avatars here
```

Everything else under `/api/v1/*` goes to `bi-dashboards-service`. See
`next.config.js` in the frontend repo for the dev-time rewrite rules — your
prod ingress must implement the same routing.

## Auth model

Authentication is delegated to Keycloak. Every request to `/api/v1/*` must
carry a Bearer access token. On every request:

1. `JWTBearer` (in `app/middleware/auth_bearer.py`) decodes the token. By
   default the signature is **not** verified (matches bi-dashboards' posture
   — trust the gateway). Set `KEYCLOAK_VERIFY_SIGNATURE=true` to switch on
   RS256 verification via the realm's JWKS endpoint with automatic key
   rotation handling.
2. `Authorization(Group.ICP_FAMILY_TREE_DASHBOARD)` (in
   `app/middleware/authorization.py`) checks that the user's `groups` claim
   contains either `ADMIN` or `ICP-FAMILY-TREE-DASHBOARD`.

To grant access in Keycloak:
- Create a group named `ICP-FAMILY-TREE-DASHBOARD` (bare name, not a full
  path).
- Ensure the client has a "Group Membership" mapper named `groups`, with
  "Full group path" off and "Add to access token" on.
- Add the relevant users to the group.

No user records are stored in this service. Keycloak is the source of truth.

## What changed from the previous version

Removed:
- `app/auth/authentication.py` — auto-provisioning into in-memory store.
- `app/db/user_store.py` — in-memory user dict; reset on every pod restart,
  inconsistent across replicas.
- `app/models/user.py` and `app/models/user_db.py` — user models duplicating
  Keycloak data.
- `app/routers/users.py` — unauthenticated CRUD against the in-memory dict.
- `app/routers/user_management.py` — activation/role-refresh endpoints that
  mutated a soon-to-be-overwritten in-memory record.
- `app/routers/auth.py` — `/me`, `/keycloak-config`, `/logout` endpoints that
  the frontend doesn't call.
- `app/middleware/rbac.py` — `require_roles` decorator superseded by the
  `Authorization` dependency.
- `app/services/role_mapping.py` and `config/role_mapping.yaml` — group →
  role translation layer; the codebase now uses Keycloak groups directly,
  matching bi-dashboards.

Added:
- `app/common/errors.py` — error-code envelope identical to bi-dashboards.
- `app/core/config.py` — single env-driven config loader.
- `app/core/group.py` — `Group` enum, including `ICP_FAMILY_TREE_DASHBOARD`.
- `app/middleware/auth_bearer.py` — `JWTBearer` with optional JWKS RS256
  verification.
- `app/middleware/authorization.py` — group-based access control dependency.
- `app/middleware/security_header.py` — HSTS / X-Frame-Options / etc.
- `app/utill/LoggingHandler.py` — log format matching bi-dashboards.
- `slowapi` rate limiter and validation/HTTP exception handlers in `main.py`.

Kept unchanged:
- `app/services/graph_service.py` — Cypher queries and tree assembly.
- `app/db/neo4j_client.py` — driver wrapper (now reads from `core.config`).

## Environment variables

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `NEO4J_URI` | yes | — | e.g. `bolt://neo4j:7687` |
| `NEO4J_USER` | yes | — | |
| `NEO4J_PASSWORD` | yes | — | |
| `NEO4J_DB` | no | `neo4j` | |
| `KEYCLOAK_URL` | yes | — | e.g. `https://keycloak.example.com` |
| `KEYCLOAK_REALM` | yes | — | e.g. `icp` |
| `KEYCLOAK_CLIENT_ID` | no | `icp-frontend` | informational |
| `KEYCLOAK_VERIFY_SIGNATURE` | no | `false` | `true` enables JWKS RS256 verification |
| `PORT` | no | `8080` | matches bi-dashboards |
| `ALLOW_ORIGINS` | no | `*` | comma-separated. Use real origins when `allow_credentials` matters |
| `RATE_LIMIT` | no | `50` | requests/min/IP |
| `LOG_DIR` | no | `/app/logs` | |
| `BUILD_VERSION` | no | `0.1.0` | shown on `/healthcheck` |
| `PATCH_VERSION` | no | date | shown on `/healthcheck` |

## Local dev

```bash
export NEO4J_PASSWORD=changeme
export KEYCLOAK_URL=https://keycloak.dev.example.com
export KEYCLOAK_REALM=icp
docker network create common_network   # one-off if it doesn't exist
docker compose up --build
```

Service is then on `http://localhost:3001` (host port; container is 8080).
Health: `curl http://localhost:3001/healthcheck`.
