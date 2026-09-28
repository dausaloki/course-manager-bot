"""Provider session persistence.

Stores ONLY the opaque session token + expiry in the ``sessions`` table.
Raw passwords are used once for the login API call and are never written
to disk, database or logs.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update

from app_api.models import ProviderSession
from database.db import get_session
from database.models import AppSession, User
from utils.logger import get_logger, log_event

logger = get_logger(__name__)


def ensure_user(telegram_id: int, username: str = "", is_admin: bool = False) -> int:
    """Get or create the local user row; returns its primary key."""
    with get_session() as session:
        user = session.execute(
            select(User).where(User.telegram_id == telegram_id)
        ).scalar_one_or_none()
        if user is None:
            user = User(telegram_id=telegram_id, username=username or "", is_admin=is_admin)
            session.add(user)
            session.flush()
        else:
            user.username = username or user.username
            user.is_admin = is_admin or user.is_admin
        return user.id


def save_session(telegram_id: int, ps: ProviderSession) -> None:
    """Deactivate old sessions and persist the new token."""
    user_pk = ensure_user(telegram_id)
    with get_session() as session:
        session.execute(
            update(AppSession).where(AppSession.user_id == user_pk).values(active=False)
        )
        session.add(AppSession(
            user_id=user_pk,
            account_label=ps.account_label[:190],
            session_token=ps.token,
            expires_at=ps.expires_at,
            active=True,
        ))
    log_event("INFO", "login_success", f"account={ps.account_label}")


def load_session(telegram_id: int) -> ProviderSession | None:
    """Load an active, unexpired stored session (or None)."""
    with get_session() as session:
        row = session.execute(
            select(AppSession)
            .join(User, User.id == AppSession.user_id)
            .where(User.telegram_id == telegram_id, AppSession.active.is_(True))
            .order_by(AppSession.id.desc())
        ).scalars().first()
        if row is None:
            return None
        if row.expires_at is not None:
            exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
            if exp <= datetime.now(timezone.utc):
                row.active = False
                return None
        return ProviderSession(token=row.session_token,
                               account_label=row.account_label,
                               expires_at=row.expires_at)


def clear_session(telegram_id: int) -> None:
    with get_session() as session:
        user = session.execute(
            select(User).where(User.telegram_id == telegram_id)
        ).scalar_one_or_none()
        if user is not None:
            session.execute(
                update(AppSession).where(AppSession.user_id == user.id).values(active=False)
            )
    log_event("INFO", "logout", f"telegram_id={telegram_id}")
