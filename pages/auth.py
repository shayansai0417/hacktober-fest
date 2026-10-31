"""Public sign-in, account creation, verification, and recovery screens."""

from __future__ import annotations

import html
import json
from urllib.parse import urljoin

import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from config import settings
from database.db import session_scope
from database.models import Teacher, utcnow
from services.auth_service import authenticate, consume_token, create_login_session, create_teacher, issue_token, resolve_login_session, revoke_login_session, send_token_email

_AUTH_COOKIE = "papergrade_auth"


def establish_session(session, teacher: Teacher, remember: bool = False) -> str:
    auth_session, raw_token = create_login_session(session, teacher, remember)
    st.session_state.auth_teacher_id = teacher.id
    st.session_state.auth_session_version = teacher.session_version
    st.session_state.auth_login_session_id = auth_session.id
    st.session_state.auth_expires_at = auth_session.expires_at.isoformat()
    st.session_state.pop("auth_screen", None)
    st.session_state.auth_flash = f"Welcome, {teacher.name}."
    st.session_state.workspace_mode = "demo" if teacher.is_demo_account else ("demo" if settings.demo_mode else "live")
    st.session_state.workspace_mode_radio = "Demonstration mode" if st.session_state.workspace_mode == "demo" else "Live Gemma mode"
    st.session_state.gemma_ready = settings.live_ready
    return raw_token


def _write_browser_cookie(raw_token: str | None, *, remember: bool = False, redirect: str | None = None) -> None:
    secure = "; Secure" if settings.effective_app_url.casefold().startswith("https://") else ""
    value = json.dumps(raw_token or "")
    max_age = "; Max-Age=1209600" if raw_token and remember else ("; Max-Age=0" if not raw_token else "")
    destination = json.dumps(redirect) if redirect else "null"
    components.html(
        f"""<script>
        const token = {value};
        document.cookie = {_AUTH_COOKIE!r} + '=' + encodeURIComponent(token) + '; Path=/; SameSite=Strict{secure}{max_age}';
        const destination = {destination};
        if (destination) window.parent.location.replace(destination);
        </script>""",
        width=1,
        height=1,
    )


def _open_authenticated_workspace() -> None:
    """Switch pages within the current Streamlit session after authentication."""
    dashboard = st.session_state.get("page_objects", {}).get("Dashboard")
    if dashboard is None:
        st.rerun()
    st.switch_page(dashboard)


def restore_browser_session() -> None:
    if st.session_state.get("auth_teacher_id"):
        return
    try:
        raw_token = st.context.cookies.get(_AUTH_COOKIE)
    except Exception:
        raw_token = None
    if not raw_token:
        return
    with session_scope() as session:
        resolved = resolve_login_session(session, raw_token)
        if resolved is not None:
            auth_session, teacher = resolved
            st.session_state.auth_teacher_id = teacher.id
            st.session_state.auth_session_version = teacher.session_version
            st.session_state.auth_login_session_id = auth_session.id
            st.session_state.auth_expires_at = auth_session.expires_at.isoformat()
            st.session_state.auth_teacher_name = teacher.name
            st.session_state.auth_teacher_email = teacher.email
            st.session_state.auth_is_demo = teacher.is_demo_account
            st.session_state.workspace_mode = "demo" if teacher.is_demo_account or settings.demo_mode else "live"
            st.session_state.workspace_mode_radio = "Demonstration mode" if st.session_state.workspace_mode == "demo" else "Live Gemma mode"
            st.session_state.gemma_ready = settings.live_ready
        else:
            st.session_state._auth_cookie_invalid = True


def logout() -> None:
    session_id = st.session_state.get("auth_login_session_id")
    owner_id = st.session_state.get("auth_teacher_id")
    if session_id and owner_id:
        with session_scope() as session:
            revoke_login_session(session, session_id, owner_id)
    welcome = st.session_state.get("page_objects", {}).get("Welcome")
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    _write_browser_cookie(None)
    if welcome is not None:
        st.switch_page(welcome)
    st.rerun()


def _set_auth_style() -> None:
    st.markdown("""<style>
      [data-testid="stMainBlockContainer"]{max-width:1100px;padding-top:4vh!important}
      [data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"]{display:none!important}
      [data-testid="stAppViewContainer"]>.main{width:100%!important;margin-left:0!important}
      .auth-brand{color:#F5F3FF;font:800 19px Manrope,sans-serif;letter-spacing:-.04em}
      .auth-brand b{color:#A78BFA}
      .auth-sub{color:#A1A1AA;font-size:13px;margin:8px 0 23px}
      .auth-kicker{color:#A78BFA;font-size:9px;letter-spacing:.16em;font-weight:800}
      .auth-title{color:#F5F3FF;font:800 31px/1.15 Manrope,sans-serif;letter-spacing:-.05em;margin:7px 0}
      .auth-card{background:#171719;border:1px solid #35333D;border-radius:16px;padding:27px 30px 22px;box-shadow:0 18px 50px #0004}
      .auth-demo{border:1px solid #514266;background:#211D29;border-radius:10px;padding:13px 15px;color:#DDD4EF;font-size:12px;line-height:1.65;margin:10px 0 14px}
      .auth-demo strong{color:#E9DFFF}
      .auth-footer{color:#8E8996;font-size:11px;text-align:center;padding-top:13px}
      .auth-footer a{color:#C4B5FD}
      @media(max-width:620px){[data-testid="stMainBlockContainer"]{padding:.5rem .8rem 2rem!important}.auth-card{padding:21px 17px}.auth-title{font-size:27px}}
    </style>""", unsafe_allow_html=True)


def _begin_session_for_demo() -> None:
    if not settings.demo_login_available:
        st.error("The demo account is not enabled in this deployment.")
        return
    with session_scope() as session:
        teacher = session.scalar(select(Teacher).where(Teacher.is_demo_account.is_(True)))
        if teacher is None:
            st.error("The demo account is not available in this deployment.")
            return
        raw_token = establish_session(session, teacher)
    _write_browser_cookie(raw_token)
    _open_authenticated_workspace()


def _render_token_action() -> bool:
    action = st.query_params.get("auth_action")
    raw = st.query_params.get("token")
    if not action or not raw:
        return False
    if action == "verify_email":
        with session_scope() as session:
            teacher = consume_token(session, raw, "verify_email")
            email = teacher.email if teacher else None
        st.query_params.clear()
        if email:
            st.success("Email verified. You can now sign in.")
        else:
            st.error("This verification link is invalid, expired, or already used.")
        st.button("Return to sign in", on_click=lambda: st.session_state.update(auth_screen="login"))
        return True
    if action == "password_reset":
        st.markdown('<div class="auth-kicker">SECURE ACCOUNT RECOVERY</div><div class="auth-title">Choose a new password</div>', unsafe_allow_html=True)
        with st.form("complete_password_reset"):
            new_password = st.text_input("New password", type="password")
            confirm = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Reset password", type="primary", use_container_width=True)
        if submitted:
            if new_password != confirm:
                st.error("The passwords do not match.")
            else:
                from services.auth_service import hash_password, validate_password
                try:
                    validate_password(new_password)
                    with session_scope() as session:
                        teacher = consume_token(session, raw, "password_reset")
                        if teacher is None:
                            raise ValueError("This reset link is invalid, expired, or already used.")
                        teacher.password_hash = hash_password(new_password)
                        teacher.session_version += 1
                        for auth_session in teacher.auth_sessions:
                            if auth_session.revoked_at is None:
                                auth_session.revoked_at = utcnow()
                    st.query_params.clear()
                    st.success("Password reset. Sign in with your new password.")
                    st.session_state.auth_screen = "login"
                except ValueError as exc:
                    st.error(str(exc))
        return True
    st.query_params.clear()
    return False


def render() -> None:
    _set_auth_style()
    if st.session_state.pop("_auth_cookie_invalid", False):
        _write_browser_cookie(None)
    _, center, _ = st.columns([1.1, 1.35, 1.1])
    with center:
        st.markdown('<div class="auth-brand">PaperGrade <b>AI</b></div><div class="auth-sub">Teacher-led assessment workspace</div>', unsafe_allow_html=True)
        if _render_token_action():
            return
        flash = st.session_state.pop("auth_flash", None)
        if flash:
            st.success(flash)
        screen = st.session_state.get("auth_screen", "login")
        if screen == "signup":
            _render_signup()
        elif screen == "forgot":
            _render_forgot_password()
        elif screen == "verify":
            _render_resend_verification()
        else:
            _render_login()


def _render_login() -> None:
    st.markdown('<div class="auth-kicker">WELCOME BACK</div><div class="auth-title">Sign in to your workspace</div><p class="auth-sub">Your classes and assessment records stay in your teacher account.</p>', unsafe_allow_html=True)
    if settings.demo_login_available:
        st.markdown(
            f'<div class="auth-demo"><strong>Demo account</strong><br>Email: {html.escape(settings.demo_login_email)}<br>Password: {html.escape(settings.demo_login_password)}<br>Sample workspace · Gemma runs when GEMMA_API_KEY is configured.</div>',
            unsafe_allow_html=True,
        )
        if st.button("Continue as demo teacher", type="primary", use_container_width=True):
            _begin_session_for_demo()
            return
    with st.form("teacher_login"):
        email = st.text_input("Email", placeholder="you@school.edu")
        password = st.text_input("Password", type="password", key="login_password")
        remember = st.checkbox("Remember me for 14 days")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submitted:
        try:
            raw_token = None
            with session_scope() as session:
                teacher, error = authenticate(session, email, password)
                if teacher:
                    raw_token = establish_session(session, teacher, remember)
            if raw_token is None:
                st.error(error)
            else:
                _write_browser_cookie(raw_token, remember=remember)
                _open_authenticated_workspace()
        except IntegrityError:
            st.error("Sign-in is temporarily unavailable. Please retry in a moment.")
    first, second = st.columns(2)
    with first:
        if st.button("Forgot password?", use_container_width=True):
            st.session_state.auth_screen = "forgot"
            st.rerun()
    with second:
        if st.button("Create account", use_container_width=True):
            st.session_state.auth_screen = "signup"
            st.rerun()
    if st.button("Resend verification email", use_container_width=True):
        st.session_state.auth_screen = "verify"
        st.rerun()


def _render_signup() -> None:
    st.markdown('<div class="auth-kicker">TEACHER ACCOUNT</div><div class="auth-title">Create your workspace</div><p class="auth-sub">Your student and assessment data will be private to your account.</p>', unsafe_allow_html=True)
    name = st.text_input("Full name", key="signup_name")
    email = st.text_input("Email", key="signup_email")
    institution = st.text_input("School / institution", key="signup_institution")
    designation = st.text_input("Designation (optional)", key="signup_designation")
    specialization = st.text_input("Subject specialization (optional)", key="signup_specialization")
    password = st.text_input("Password", type="password", key="signup_password", help="Use at least 12 characters.")
    confirm = st.text_input("Confirm password", type="password", key="signup_confirm")
    strength = min(5, (len(password) >= 12) + (len(password) >= 16) + any(c.islower() for c in password) + any(c.isupper() for c in password) + any(c.isdigit() or not c.isalnum() for c in password))
    labels = ["Add a longer password", "Weak", "Fair", "Good", "Strong", "Very strong"]
    if password:
        st.progress(strength / 5, text=f"Password strength · {labels[strength]}")
    terms = st.checkbox("I agree to use PaperGrade AI responsibly and keep the teacher in control of final marks.")
    submitted = st.button("Create teacher account", type="primary", use_container_width=True)
    if submitted:
        if password != confirm:
            st.error("The passwords do not match.")
        elif not terms:
            st.error("Accept the terms to create your account.")
        else:
            try:
                raw_token = None
                with session_scope() as session:
                    teacher, token = create_teacher(session, name=name, email=email, password=password, institution=institution, designation=designation, subject_specialization=specialization)
                    teacher_info = {"id": teacher.id, "name": teacher.name, "email": teacher.email}
                    if token is None:
                        raw_token = establish_session(session, teacher)
                if token:
                    send_token_email(teacher_info["email"], teacher_info["name"], token, "verify_email", settings.effective_app_url)
                    st.success("Account created. Check your email for a one-time verification link.")
                    st.session_state.auth_screen = "login"
                else:
                    _write_browser_cookie(raw_token)
                    _open_authenticated_workspace()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
            except IntegrityError:
                st.error("An account already uses this email. Try signing in or resetting its password.")
            except Exception:
                # The account and its verification token are committed before SMTP
                # delivery. Keep the teacher informed and direct them to resend.
                st.error("Your account was created, but the verification email could not be sent. Use 'Resend verification email' after SMTP is restored.")
    if st.button("Back to sign in"):
        st.session_state.auth_screen = "login"
        st.rerun()


def _render_forgot_password() -> None:
    st.markdown('<div class="auth-kicker">ACCOUNT RECOVERY</div><div class="auth-title">Reset your password</div><p class="auth-sub">We’ll send a one-time link if this email belongs to an account.</p>', unsafe_allow_html=True)
    with st.form("request_password_reset"):
        email = st.text_input("Account email")
        submitted = st.form_submit_button("Send reset link", type="primary", use_container_width=True)
    if submitted:
        if settings.smtp_ready:
            with session_scope() as session:
                teacher = session.scalar(select(Teacher).where(func.lower(Teacher.email) == email.strip().casefold(), Teacher.is_demo_account.is_(False)))
                if teacher and teacher.password_hash:
                    raw = issue_token(session, teacher, "password_reset")
                    target = (teacher.email, teacher.name)
                else:
                    target = None
            if target:
                try:
                    send_token_email(target[0], target[1], raw, "password_reset", settings.effective_app_url)
                except Exception:
                    # Keep account existence private; avoid rendering SMTP/server details.
                    pass
        st.success("If the address is eligible, a password reset link will arrive shortly.")
    if st.button("Back to sign in"):
        st.session_state.auth_screen = "login"
        st.rerun()


def _render_resend_verification() -> None:
    st.markdown('<div class="auth-kicker">EMAIL VERIFICATION</div><div class="auth-title">Verify your email</div><p class="auth-sub">If verification is pending, we’ll send a fresh one-time link.</p>', unsafe_allow_html=True)
    with st.form("resend_verification"):
        email = st.text_input("Account email")
        submitted = st.form_submit_button("Send verification link", type="primary", use_container_width=True)
    if submitted:
        if settings.smtp_ready:
            with session_scope() as session:
                teacher = session.scalar(select(Teacher).where(func.lower(Teacher.email) == email.strip().casefold(), Teacher.email_verified.is_(False), Teacher.is_demo_account.is_(False)))
                if teacher:
                    raw = issue_token(session, teacher, "verify_email")
                    target = (teacher.email, teacher.name)
                else:
                    target = None
            if target:
                try:
                    send_token_email(target[0], target[1], raw, "verify_email", settings.effective_app_url)
                except Exception:
                    pass
        st.success("If the account requires verification, a new link will arrive shortly.")
    if st.button("Back to sign in"):
        st.session_state.auth_screen = "login"
        st.rerun()
