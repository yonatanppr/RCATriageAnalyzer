"""Authentication and authorization helpers."""

import base64
import json
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.domain.models import AuthPrincipal, UserRole


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool
    shared_token: str | None


def _auth_settings() -> AuthSettings:
    settings = get_settings()
    enabled = str(getattr(settings, "auth_enabled", True)).lower() in {"1", "true", "yes"}
    shared_token = getattr(settings, "auth_shared_token", None)
    return AuthSettings(enabled=enabled, shared_token=shared_token)


def _decode_claims(token: str) -> dict:
    # MVP token format: base64url encoded JSON body, optionally prefixed with "dev."
    raw = token[4:] if token.startswith("dev.") else token
    try:
        padded = raw + "=" * ((4 - len(raw) % 4) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid auth token: {exc}") from exc


def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AuthPrincipal:
    cfg = _auth_settings()
    if not cfg.enabled:
        return AuthPrincipal(subject="dev-local", role=UserRole.admin, services=["*"], can_ingest=True)

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")

    token = credentials.credentials.strip()
    if cfg.shared_token and token == cfg.shared_token:
        return AuthPrincipal(subject="shared-token", role=UserRole.admin, services=["*"], can_ingest=True)

    claims = _decode_claims(token)
    role_raw = str(claims.get("role", UserRole.viewer.value))
    services = claims.get("services", [])
    if not isinstance(services, list):
        services = []
    return AuthPrincipal(
        subject=str(claims.get("sub", "unknown")),
        role=UserRole(role_raw) if role_raw in UserRole._value2member_map_ else UserRole.viewer,
        services=[str(s) for s in services],
        can_ingest=bool(claims.get("can_ingest", False)),
    )


def authorize_service(principal: AuthPrincipal, service: str) -> None:
    if principal.role == UserRole.admin:
        return
    if "*" in principal.services:
        return
    if service in principal.services:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"forbidden for service={service}")


def require_ingest(principal: AuthPrincipal) -> None:
    if principal.role == UserRole.admin or principal.can_ingest:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ingest permission required")

