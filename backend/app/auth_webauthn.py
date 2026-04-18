"""
WebAuthn (Passkey) Authentication — passwordless, phishing-resistant auth.
Single-owner model: only 1 user, multiple passkeys (devices).
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit as _log_audit
from app.config import settings
from app.db.models import AuthSession, Owner, WebAuthnCredential
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Challenge storage: Redis with 5-minute TTL (security fix for multi-instance deployments)
# Key pattern: "webauthn:challenge:{id}"


# ─── Rate Limiting for Auth Endpoints ────────────────────────────────────────

_AUTH_RATE_LIMIT = 10  # attempts per minute per IP (higher for passkey retries)
_AUTH_RATE_WINDOW = 60  # seconds


async def _check_auth_rate_limit(request: Request, redis_client) -> None:
    """Check if IP has exceeded auth rate limit. Raises 429 if exceeded."""
    ip = _get_client_ip_from_request(request)
    key = f"ratelimit:webauthn:{ip}"

    try:
        # Increment counter
        current = await redis_client.incr(key)
        if current == 1:
            # First request — set expiration
            await redis_client.expire(key, _AUTH_RATE_WINDOW)

        if current > _AUTH_RATE_LIMIT:
            logger.warning(f"Rate limit exceeded for IP {ip} (WebAuthn endpoint)")
            raise HTTPException(
                status_code=429,
                detail=f"Too many attempts. Please wait {_AUTH_RATE_WINDOW} seconds before trying again.",
                headers={"Retry-After": str(_AUTH_RATE_WINDOW)},
            )
    except HTTPException:
        raise
    except Exception as e:
        # Redis error — fail open
        logger.debug(f"Rate limiter error: {e}, allowing request")


def _get_client_ip_from_request(request: Request) -> str:
    """Extract client IP from request, accounting for proxies."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

RP_ID = settings.webauthn_rp_id if hasattr(settings, "webauthn_rp_id") else "localhost"
RP_NAME = "AI Trading Agent"
ORIGIN = settings.webauthn_origin if hasattr(settings, "webauthn_origin") else "http://localhost:3000"
CHALLENGE_TTL = 300  # 5 minutes


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_redis(request: Request):
    """Get Redis client from app state."""
    redis_client = getattr(request.app.state, "redis", None)
    if not redis_client:
        raise HTTPException(
            status_code=503,
            detail="Redis not available — WebAuthn requires Redis for challenge storage"
        )
    return redis_client


async def _store_challenge(redis_client, key: str, challenge: bytes) -> None:
    """Store challenge in Redis with TTL."""
    await redis_client.setex(f"webauthn:challenge:{key}", CHALLENGE_TTL, challenge)


async def _get_and_delete_challenge(redis_client, key: str) -> bytes | None:
    """Get and delete challenge from Redis (atomic)."""
    challenge_key = f"webauthn:challenge:{key}"
    challenge = await redis_client.get(challenge_key)
    if challenge:
        await redis_client.delete(challenge_key)
        # Redis returns bytes, ensure we return bytes
        if isinstance(challenge, bytes):
            return challenge
        return challenge.encode() if isinstance(challenge, str) else bytes(challenge)
    return None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _create_jwt(owner_id: int, jti: str) -> str:
    """Create a JWT token for session."""
    from jose import jwt
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {"sub": str(owner_id), "jti": jti, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def _verify_jwt(token: str) -> dict | None:
    """Verify JWT and return payload."""
    from jose import jwt
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except Exception:
        return None



# ─── Setup Check ──────────────────────────────────────────────────────────────

class SetupStatus(BaseModel):
    is_setup_complete: bool
    owner_name: str | None = None


@router.get("/setup-status")
async def get_setup_status(db: AsyncSession = Depends(get_db)):
    """Check if initial setup (first passkey registration) is complete."""
    result = await db.execute(select(Owner).limit(1))
    owner = result.scalar_one_or_none()
    if not owner or not owner.is_setup_complete:
        return SetupStatus(is_setup_complete=False)
    return SetupStatus(is_setup_complete=True, owner_name=owner.display_name)


# ─── Registration (first-time setup) ─────────────────────────────────────────

class RegisterOptionsRequest(BaseModel):
    display_name: str = "Admin"


@router.post("/register/options")
async def register_options(
    req: RegisterOptionsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Generate WebAuthn registration challenge. Only works if setup not complete."""
    from webauthn import generate_registration_options
    from webauthn.helpers.structs import AuthenticatorSelectionCriteria, ResidentKeyRequirement

    redis_client = _get_redis(request)

    # Check if already set up
    result = await db.execute(select(Owner).limit(1))
    owner = result.scalar_one_or_none()
    if owner and owner.is_setup_complete:
        # Allow adding more passkeys if setup is complete (for backup devices)
        pass
    elif not owner:
        owner = Owner(display_name=req.display_name)
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

    # Get existing credentials to exclude
    creds_result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.owner_id == owner.id)
    )
    existing_creds = creds_result.scalars().all()

    from webauthn.helpers.structs import PublicKeyCredentialDescriptor

    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=str(owner.id).encode(),
        user_name=owner.display_name,
        user_display_name=owner.display_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=c.credential_id)
            for c in existing_creds
        ],
    )

    # Store challenge for verification in Redis with TTL
    await _store_challenge(redis_client, f"register:{owner.id}", options.challenge)

    from webauthn.helpers import options_to_json
    return {"options": options_to_json(options), "owner_id": owner.id}


class RegisterVerifyRequest(BaseModel):
    owner_id: int
    credential: dict
    device_name: str = "Default Device"


@router.post("/register/verify")
async def register_verify(
    req: RegisterVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify registration response and store credential."""
    from webauthn import verify_registration_response
    from webauthn.helpers import parse_registration_credential_json
    import json

    redis_client = _get_redis(request)
    challenge = await _get_and_delete_challenge(redis_client, f"register:{req.owner_id}")
    if not challenge:
        raise HTTPException(status_code=400, detail="Registration challenge expired")

    try:
        credential = parse_registration_credential_json(json.dumps(req.credential))
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Registration failed: {e}")

    # Store credential
    new_cred = WebAuthnCredential(
        owner_id=req.owner_id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        device_name=req.device_name,
    )
    db.add(new_cred)

    # Mark setup as complete
    await db.execute(
        update(Owner).where(Owner.id == req.owner_id).values(is_setup_complete=True)
    )
    await db.commit()

    # Reset middleware cache so it starts enforcing auth
    from app.middleware.auth import AuthMiddleware
    AuthMiddleware.reset_cache()

    await _log_audit(db, "passkey_registered", resource=f"device:{req.device_name}")
    logger.info(f"Passkey registered: {req.device_name} for owner {req.owner_id}")

    return {"status": "registered", "device_name": req.device_name}


# ─── Login ────────────────────────────────────────────────────────────────────

@router.post("/login/options")
async def login_options(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Generate WebAuthn login challenge."""
    from webauthn import generate_authentication_options

    redis_client = _get_redis(request)

    result = await db.execute(select(Owner).limit(1))
    owner = result.scalar_one_or_none()
    if not owner or not owner.is_setup_complete:
        raise HTTPException(status_code=400, detail="Setup not complete. Register a passkey first.")

    creds_result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.owner_id == owner.id)
    )
    creds = creds_result.scalars().all()

    from webauthn.helpers.structs import PublicKeyCredentialDescriptor

    options = generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=c.credential_id)
            for c in creds
        ],
    )

    # Store challenge in Redis with TTL
    await _store_challenge(redis_client, "login", options.challenge)

    from webauthn.helpers import options_to_json
    return {"options": options_to_json(options)}


class LoginVerifyRequest(BaseModel):
    credential: dict


@router.post("/login/verify")
async def login_verify(
    req: LoginVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Verify login assertion and issue JWT cookie."""
    from webauthn import verify_authentication_response
    from webauthn.helpers import parse_authentication_credential_json
    import json

    redis_client = _get_redis(request)
    # Rate limit check
    await _check_auth_rate_limit(request, redis_client)

    challenge = await _get_and_delete_challenge(redis_client, "login")
    if not challenge:
        raise HTTPException(status_code=400, detail="Login challenge expired")

    credential = parse_authentication_credential_json(json.dumps(req.credential))

    # Find the credential in DB
    result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == credential.raw_id
        )
    )
    stored_cred = result.scalar_one_or_none()
    if not stored_cred:
        raise HTTPException(status_code=401, detail="Unknown credential")

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            credential_public_key=stored_cred.public_key,
            credential_current_sign_count=stored_cred.sign_count,
        )
    except Exception as e:
        await _log_audit(db, "login_failed", ip=request.client.host if request.client else None, success=False)
        raise HTTPException(status_code=401, detail=f"Authentication failed: {e}")

    # Update sign count
    stored_cred.sign_count = verification.new_sign_count
    stored_cred.last_used_at = datetime.utcnow()

    # Create session
    jti = secrets.token_urlsafe(32)
    session = AuthSession(
        owner_id=stored_cred.owner_id,
        jwt_jti=jti,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        expires_at=datetime.utcnow() + timedelta(hours=settings.jwt_expire_hours),
    )
    db.add(session)
    await db.commit()

    # Issue JWT as httpOnly cookie
    token = _create_jwt(stored_cred.owner_id, jti)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.jwt_expire_hours * 3600,
        path="/",
    )

    await _log_audit(db, "login", ip=request.client.host if request.client else None)
    logger.info(f"Owner logged in via passkey: {stored_cred.device_name}")

    return {"status": "authenticated", "display_name": stored_cred.device_name}


# ─── Session Management ───────────────────────────────────────────────────────

@router.post("/logout")
async def logout(response: Response, session: str | None = Cookie(None),
                 db: AsyncSession = Depends(get_db)):
    """Revoke current session and clear cookie."""
    if session:
        payload = _verify_jwt(session)
        if payload and payload.get("jti"):
            await db.execute(
                update(AuthSession)
                .where(AuthSession.jwt_jti == payload["jti"])
                .values(revoked_at=datetime.utcnow())
            )
            await db.commit()

    response.delete_cookie("session", path="/")
    return {"status": "logged_out"}


@router.get("/me")
async def get_me(session: str | None = Cookie(None), db: AsyncSession = Depends(get_db)):
    """Check current session. Returns owner info or 401."""
    # Check setup status first
    result = await db.execute(select(Owner).limit(1))
    owner = result.scalar_one_or_none()
    if not owner or not owner.is_setup_complete:
        return {"auth_enabled": False, "setup_required": True}

    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = _verify_jwt(session)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid session")

    # Check session not revoked
    jti = payload.get("jti")
    if jti:
        sess_result = await db.execute(
            select(AuthSession).where(AuthSession.jwt_jti == jti, AuthSession.revoked_at.is_(None))
        )
        if not sess_result.scalar_one_or_none():
            raise HTTPException(status_code=401, detail="Session revoked")

    return {
        "auth_enabled": True,
        "authenticated": True,
        "owner_name": owner.display_name,
    }


@router.get("/sessions")
async def list_sessions(session: str | None = Cookie(None), db: AsyncSession = Depends(get_db)):
    """List all active sessions."""
    result = await db.execute(
        select(AuthSession)
        .where(AuthSession.revoked_at.is_(None), AuthSession.expires_at > datetime.utcnow())
        .order_by(AuthSession.created_at.desc())
    )
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "created_at": s.created_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
        }
        for s in sessions
    ]
