"""
JWT bearer authentication.

Same interface as bi-dashboards-service/middleware/auth_bearer.py — returns a
`user_context` dict with name/username/user_id/email/groups — so the
Authorization dependency reads exactly the same fields. The difference is
that this one validates the token signature against the Keycloak realm's
JWKS by default. Set KEYCLOAK_VERIFY_SIGNATURE=false to match bi-dashboards'
trust-the-gateway posture.
"""
from typing import Any, Dict, Optional

import httpx
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt as jose_jwt
from jose import JWTError

from app.common.errors import ErrorCode, handle_errors
from app.core.config import config
from app.utill.LoggingHandler import LoggingHandler

logger = LoggingHandler.get_logger(__name__)

_JWKS_URL = (
    f"{config.keycloak_url}/realms/{config.keycloak_realm}"
    "/protocol/openid-connect/certs"
)

# Built-in Keycloak roles that are not application-level groups
_SYSTEM_ROLES = {
    "offline_access",
    "uma_authorization",
    f"default-roles-{config.keycloak_realm}",
}

# Process-local JWKS cache; refreshed when we see an unknown kid (key rotation).
_jwks_cache: Optional[Dict[str, Any]] = None


def _fetch_jwks() -> Dict[str, Any]:
    logger.info(f"keycloak.jwks.fetch | url={_JWKS_URL}")
    with httpx.Client(timeout=10.0) as client:
        response = client.get(_JWKS_URL)
        response.raise_for_status()
        return response.json()


def _get_jwks(force_refresh: bool = False) -> Dict[str, Any]:
    global _jwks_cache
    if force_refresh or _jwks_cache is None:
        _jwks_cache = _fetch_jwks()
    return _jwks_cache


def _find_key(jwks: Dict[str, Any], kid: str) -> Optional[Dict[str, Any]]:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


class JWTBearer(HTTPBearer):
    """
    Returns a dict identical in shape to bi-dashboards' JWTBearer so the same
    Authorization dependency can be used unchanged.
    """

    def __init__(self, auto_error: bool = True):
        super().__init__(auto_error=auto_error)
        self.error_context = "ValidationError occurred"

    async def __call__(self, request: Request) -> Dict[str, Any]:
        try:
            credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        except Exception:
            handle_errors(
                error_code=ErrorCode.NOT_AUTHENTICATED_001,
                error_context="AuthenticationError occurred",
                status_code=403,
            )

        if not credentials:
            handle_errors(
                error_code=ErrorCode.UNAUTHORIZED_002,
                error_context=self.error_context,
                status_code=401,
            )

        if credentials.scheme != "Bearer":
            handle_errors(
                error_code=ErrorCode.UNAUTHORIZED_001,
                error_context=self.error_context,
                status_code=401,
            )

        payload = self._verify(credentials.credentials)
        if payload is None:
            handle_errors(
                error_code=ErrorCode.UNAUTHORIZED_002,
                error_context=self.error_context,
                status_code=401,
            )

        realm_access = payload.get("realm_access") or {}
        realm_roles = [r for r in (realm_access.get("roles") or []) if r not in _SYSTEM_ROLES]
        # Keycloak's "Group Membership" mapper puts groups on a top-level `groups`
        # claim. bi-dashboards reads exactly this — keep behaviour identical.
        # Coerce both "key absent" and "key present but null" to an empty list
        # so downstream code (Authorization dep) can iterate safely.
        groups = list(payload.get("groups") or [])

        return {
            "name": payload.get("name"),
            "username": payload.get("preferred_username"),
            "user_id": payload.get("sub"),
            "email": payload.get("email"),
            "groups": groups,
            # exposed for downstream code that wants realm roles (optional)
            "realm_roles": realm_roles,
        }

    def _verify(self, token: str) -> Optional[Dict[str, Any]]:
        # Posture-match bi-dashboards-service: trust the gateway, do not verify.
        if not config.keycloak_verify_signature:
            try:
                return jose_jwt.get_unverified_claims(token)
            except JWTError:
                handle_errors(
                    error_code=ErrorCode.UNAUTHORIZED_003,
                    error_context=self.error_context,
                    status_code=401,
                )

        try:
            unverified_header = jose_jwt.get_unverified_header(token)
        except JWTError:
            handle_errors(
                error_code=ErrorCode.UNAUTHORIZED_003,
                error_context=self.error_context,
                status_code=401,
            )

        kid = unverified_header.get("kid")
        jwks = _get_jwks()
        key = _find_key(jwks, kid)
        if key is None:
            # Key rotation: blow the cache and try once more.
            jwks = _get_jwks(force_refresh=True)
            key = _find_key(jwks, kid)
        if key is None:
            handle_errors(
                error_code=ErrorCode.UNAUTHORIZED_003,
                error_context=self.error_context,
                status_code=401,
            )

        try:
            return jose_jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except jose_jwt.ExpiredSignatureError:
            handle_errors(
                error_code=ErrorCode.UNAUTHORIZED_004,
                error_context=self.error_context,
                status_code=401,
            )
        except JWTError:
            handle_errors(
                error_code=ErrorCode.UNAUTHORIZED_003,
                error_context=self.error_context,
                status_code=401,
            )
