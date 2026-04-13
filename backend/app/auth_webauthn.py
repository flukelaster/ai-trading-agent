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

# In-memory challenge store (short-lived, per-request)
_challenges: dict[str, bytes] = {}

RP_ID = settings.webauthn_rp_id if hasattr(settings, "webauthn_rp_id") else "localhost"
RP_NAME = "AI Trading Agent"
ORIGIN = settings.webauthn_origin if hasattr(settings, "webauthn_origin") else "http://localhost:3000"


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
async def register_options(req: RegisterOptionsRequest, db: AsyncSession = Depends(get_db)):
    """Generate WebAuthn registration challenge. Only works if setup not complete."""
    from webauthn import generate_registration_options
    from webauthn.helpers.structs import AuthenticatorSelectionCriteria, ResidentKeyRequirement

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

    # Store challenge for verification
    _challenges[str(owner.id)] = options.challenge

    from webauthn.helpers import options_to_json
    return {"options": options_to_json(options), "owner_id": owner.id}


class RegisterVerifyRequest(BaseModel):
    owner_id: int
    credential: dict
    device_name: str = "Default Device"


@router.post("/register/verify")
async def register_verify(req: RegisterVerifyRequest, db: AsyncSession = Depends(get_db)):
    """Verify registration response and store credential."""
    from webauthn import verify_registration_response
    from webauthn.helpers import parse_registration_credential_json
    import json

    challenge = _challenges.pop(str(req.owner_id), None)
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
async def login_options(db: AsyncSession = Depends(get_db)):
    """Generate WebAuthn login challenge."""
    from webauthn import generate_authentication_options

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

    _challenges["login"] = options.challenge

    from webauthn.helpers import options_to_json
    return {"options": options_to_json(options)}


class LoginVerifyRequest(BaseModel):
    credential: dict


@router.post("/login/verify")
async def login_verify(req: LoginVerifyRequest, request: Request, response: Response,
                       db: AsyncSession = Depends(get_db)):
    """Verify login assertion and issue JWT cookie."""
    from webauthn import verify_authentication_response
    from webauthn.helpers import parse_authentication_credential_json
    import json

    challenge = _challenges.pop("login", None)
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
