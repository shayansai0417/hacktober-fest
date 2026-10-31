"""Password authentication, reset/verification tokens, and login throttling."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import smtplib
import ssl
import bcrypt
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import settings
from database.models import AnswerSheet, AuthSession, AuthToken, Evaluation, LoginThrottle, Teacher, UploadedPage, utcnow


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_MAX_LOGIN_FAILURES = 5
_LOGIN_WINDOW = timedelta(minutes=15)
_LOCK_DURATION = timedelta(minutes=15)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def ensure_demo_account(session: Session) -> Teacher | None:
    if not settings.demo_login_available:
        return None
    validate_password(settings.demo_login_password)
    email = normalize_email(settings.demo_login_email)
    teacher = session.scalar(select(Teacher).where(Teacher.is_demo_account.is_(True)))
    if teacher is None:
        conflict = session.scalar(select(Teacher.id).where(func.lower(Teacher.email) == email))
        if conflict is not None:
            raise RuntimeError("DEMO_LOGIN_EMAIL is already assigned to another teacher account.")
        teacher = Teacher(
            name="PaperGrade Demo Teacher",
            institution="PaperGrade AI Demonstration Workspace",
            email=email,
            password_hash=hash_password(settings.demo_login_password),
            email_verified=True,
            email_verified_at=utcnow(),
            is_demo_account=True,
        )
        session.add(teacher)
        session.flush()
    else:
        teacher.email = email
        teacher.password_hash = hash_password(settings.demo_login_password)
        teacher.email_verified = True
        teacher.email_verified_at = teacher.email_verified_at or utcnow()
    return teacher


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Use at least 12 characters for your password.")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Use at most 72 UTF-8 bytes so bcrypt will not truncate your password.")


def create_teacher(
    session: Session,
    *,
    name: str,
    email: str,
    password: str,
    institution: str,
    designation: str = "",
    subject_specialization: str = "",
) -> tuple[Teacher, str | None]:
    clean_email = normalize_email(email)
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 120:
        raise ValueError("Enter your full name (up to 120 characters).")
    if not _EMAIL_RE.fullmatch(clean_email) or len(clean_email) > 180:
        raise ValueError("Enter a valid email address.")
    validate_password(password)
    if not institution.strip():
        raise ValueError("Enter your school or institution name.")
    if session.scalar(select(Teacher.id).where(func.lower(Teacher.email) == clean_email)) is not None:
        raise ValueError("An account already uses this email. Try signing in or resetting its password.")
    needs_verification = settings.require_email_verification or settings.app_env.casefold() in {"production", "prod"}
    if needs_verification and not settings.smtp_ready:
        raise RuntimeError("Email verification is required, but SMTP is not configured. Contact the administrator.")
    teacher = Teacher(
        name=clean_name,
        email=clean_email,
        password_hash=hash_password(password),
        institution=institution.strip()[:180],
        designation=designation.strip()[:120],
        subject_specialization=subject_specialization.strip()[:180],
        email_verified=not needs_verification,
        email_verified_at=None if needs_verification else utcnow(),
    )
    session.add(teacher)
    session.flush()
    token = issue_token(session, teacher, "verify_email") if needs_verification else None
    return teacher, token


def _email_digest(email: str) -> str:
    return hmac.new(settings.auth_secret.encode("utf-8"), normalize_email(email).encode("utf-8"), hashlib.sha256).hexdigest()


def _token_digest(raw_token: str) -> str:
    return hmac.new(settings.auth_secret.encode("utf-8"), raw_token.encode("ascii"), hashlib.sha256).hexdigest()


def authenticate(session: Session, email: str, password: str) -> tuple[Teacher | None, str]:
    """Authenticate and persist a per-email lockout. Error text avoids account enumeration."""
    now = utcnow()
    digest = _email_digest(email)
    throttle = session.scalar(select(LoginThrottle).where(LoginThrottle.email_hash == digest))
    if throttle and throttle.locked_until:
        locked_until = throttle.locked_until.replace(tzinfo=timezone.utc) if throttle.locked_until.tzinfo is None else throttle.locked_until
        if locked_until > now:
            return None, "Too many sign-in attempts. Try again in about 15 minutes."
        throttle.failures = 0
        throttle.locked_until = None
        throttle.window_started_at = now

    email_clean = normalize_email(email)
    teacher = session.scalar(select(Teacher).where(func.lower(Teacher.email) == email_clean))
    valid = (teacher is not None
             and (not teacher.is_demo_account or settings.demo_login_available)
             and verify_password(teacher.password_hash, password))
    if valid and not teacher.email_verified:
        _record_failure(session, throttle, digest, now)
        return None, "Sign-in failed. Check your email and password, or verify your email first."
    if not valid:
        _record_failure(session, throttle, digest, now)
        return None, "Sign-in failed. Check your email and password."
    if throttle is not None:
        session.delete(throttle)
    return teacher, ""


def _record_failure(session: Session, throttle: LoginThrottle | None, digest: str, now: datetime) -> None:
    if throttle is None:
        throttle = LoginThrottle(email_hash=digest, failures=0, window_started_at=now)
        session.add(throttle)
        session.flush()
    window_started = throttle.window_started_at
    if window_started.tzinfo is None:
        window_started = window_started.replace(tzinfo=timezone.utc)
    if now - window_started > _LOGIN_WINDOW:
        throttle.failures = 0
        throttle.window_started_at = now
    throttle.failures += 1
    if throttle.failures >= _MAX_LOGIN_FAILURES:
        throttle.locked_until = now + _LOCK_DURATION


def issue_token(session: Session, teacher: Teacher, purpose: str, *, lifetime: timedelta | None = None) -> str:
    if purpose not in {"verify_email", "password_reset"}:
        raise ValueError("Unsupported token purpose.")
    now = utcnow()
    for existing in teacher.auth_tokens:
        if existing.purpose == purpose and existing.used_at is None:
            existing.used_at = now
    raw = secrets.token_urlsafe(32)
    session.add(AuthToken(
        teacher_id=teacher.id,
        token_hash=_token_digest(raw),
        purpose=purpose,
        expires_at=now + (lifetime or timedelta(hours=1)),
    ))
    return raw


def consume_token(session: Session, raw: str, purpose: str) -> Teacher | None:
    if not raw or purpose not in {"verify_email", "password_reset"}:
        return None
    try:
        digest = _token_digest(raw)
    except UnicodeEncodeError:
        return None
    token = session.scalar(select(AuthToken).where(AuthToken.token_hash == digest, AuthToken.purpose == purpose))
    if token is None or token.used_at is not None:
        return None
    expires = token.expires_at.replace(tzinfo=timezone.utc) if token.expires_at.tzinfo is None else token.expires_at
    if expires <= utcnow():
        return None
    token.used_at = utcnow()
    teacher = session.get(Teacher, token.teacher_id)
    if teacher is None:
        return None
    if purpose == "verify_email":
        teacher.email_verified = True
        teacher.email_verified_at = utcnow()
    return teacher


def create_login_session(session: Session, teacher: Teacher, remember: bool) -> tuple[AuthSession, str]:
    raw = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        teacher_id=teacher.id,
        token_hash=_token_digest(raw),
        session_version=teacher.session_version,
        remember=remember,
        expires_at=utcnow() + (timedelta(days=14) if remember else timedelta(hours=12)),
    )
    session.add(auth_session)
    session.flush()
    return auth_session, raw


def resolve_login_session(session: Session, raw: str) -> tuple[AuthSession, Teacher] | None:
    try:
        token_hash = _token_digest(raw)
    except UnicodeEncodeError:
        return None
    auth_session = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash, AuthSession.revoked_at.is_(None)))
    if auth_session is None:
        return None
    expires = auth_session.expires_at.replace(tzinfo=timezone.utc) if auth_session.expires_at.tzinfo is None else auth_session.expires_at
    teacher = session.get(Teacher, auth_session.teacher_id)
    if (expires <= utcnow() or teacher is None
            or (teacher.is_demo_account and not settings.demo_login_available)
            or auth_session.session_version != teacher.session_version):
        auth_session.revoked_at = utcnow()
        return None
    auth_session.last_seen_at = utcnow()
    return auth_session, teacher


def revoke_login_session(session: Session, session_id: int, teacher_id: int) -> None:
    auth_session = session.scalar(select(AuthSession).where(AuthSession.id == session_id, AuthSession.teacher_id == teacher_id))
    if auth_session is not None and auth_session.revoked_at is None:
        auth_session.revoked_at = utcnow()


def cleanup_auth_artifacts(session: Session) -> None:
    now = utcnow()
    session.query(AuthToken).filter((AuthToken.expires_at < now - timedelta(days=1)) | (AuthToken.used_at < now - timedelta(days=1))).delete(synchronize_session=False)
    session.query(AuthSession).filter((AuthSession.expires_at < now - timedelta(days=1)) | (AuthSession.revoked_at < now - timedelta(days=1))).delete(synchronize_session=False)
    session.query(LoginThrottle).filter(
        (LoginThrottle.locked_until < now) |
        ((LoginThrottle.locked_until.is_(None)) & (LoginThrottle.window_started_at < now - timedelta(days=1)))
    ).delete(synchronize_session=False)


def send_token_email(email: str, name: str, raw_token: str, purpose: str, app_url: str) -> None:
    if not settings.smtp_ready:
        raise RuntimeError("Email delivery is not configured. Contact the administrator.")
    action = "verify your email" if purpose == "verify_email" else "reset your password"
    url = f"{app_url.rstrip('/')}?auth_action={purpose}&token={raw_token}"
    message = EmailMessage()
    message["Subject"] = "PaperGrade AI · " + ("Verify your email" if purpose == "verify_email" else "Password reset")
    message["From"] = settings.smtp_from_email
    message["To"] = email
    message.set_content(f"Hello {name},\n\nUse this one-time link to {action}. It expires in one hour:\n{url}\n\nIf you did not request this, you can ignore this message.\n")
    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20) as server:
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.starttls(context=context)
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)


def change_password(session: Session, teacher: Teacher, old_password: str, new_password: str, *, keep_session_id: int | None = None) -> None:
    if not verify_password(teacher.password_hash, old_password):
        raise ValueError("Current password is incorrect.")
    validate_password(new_password)
    teacher.password_hash = hash_password(new_password)
    teacher.session_version += 1
    for auth_session in teacher.auth_sessions:
        if auth_session.id == keep_session_id and auth_session.revoked_at is None:
            auth_session.session_version = teacher.session_version
        elif auth_session.revoked_at is None:
            auth_session.revoked_at = utcnow()


def delete_teacher_workspace(session: Session, teacher_id: int, password: str) -> list[str]:
    teacher = session.get(Teacher, teacher_id)
    if teacher is None:
        raise ValueError("Teacher account not found.")
    if teacher.is_demo_account:
        raise ValueError("The shared demonstration account cannot be deleted.")
    if not verify_password(teacher.password_hash, password):
        raise ValueError("Password confirmation failed.")
    paths = session.scalars(
        select(UploadedPage.file_path)
        .join(AnswerSheet, UploadedPage.answer_sheet_id == AnswerSheet.id)
        .join(Evaluation, AnswerSheet.evaluation_id == Evaluation.id)
        .where(Evaluation.teacher_id == teacher_id)
    ).all()
    session.delete(teacher)
    return list(paths)


def remove_deleted_uploads(paths: list[str]) -> None:
    root = settings.upload_dir.resolve()
    for value in paths:
        path = Path(value).resolve()
        if root not in path.parents:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Database privacy is already enforced; a later storage sweep can
            # clean a file that was temporarily locked by the operating system.
            continue
    for token in teacher.auth_tokens:
        if token.used_at is None:
            token.used_at = utcnow()

