from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_
from sqlmodel import Session, col, select

from app.models import Order

NEW_STATUSES = ("pending", "new", "upsell_accepted", "confirmed")
CONFIRMED_STATUSES = ("confirmed",)
ITEM_LIMIT = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _hours_since(value: datetime | None, now: datetime) -> int:
    stamp = _aware(value)
    if stamp is None:
        return 0
    seconds = (now - stamp).total_seconds()
    return max(0, int(seconds // 3600))


def _no_tracking():
    return or_(
        col(Order.meta_livraison_code).is_(None),
        Order.meta_livraison_code == "",
    )


def _display_status(raw: str) -> str:
    if raw in ("pending", "upsell_accepted", "new"):
        return "new"
    if raw == "in_shipping":
        return "shipped"
    return raw or "new"


def _order_code(order: Order) -> str:
    compact = str(order.id).replace("-", "")[:6].upper()
    return f"#CFG-{compact}"


def dump_undispatched_item(order: Order, now: datetime, delayed_from: datetime | None) -> dict:
    return {
        "id": str(order.id),
        "order_id": str(order.id),
        "code": _order_code(order),
        "full_name": order.full_name,
        "client_name": order.full_name,
        "phone": order.phone_national or order.phone,
        "phone_national": order.phone_national,
        "city": order.city,
        "address": getattr(order, "address", None),
        "status": _display_status(order.status),
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "confirmed_at": order.confirmed_at.isoformat() if order.confirmed_at else None,
        "hours_delayed": _hours_since(delayed_from or order.confirmed_at or order.created_at, now),
        "hours_ago": _hours_since(order.created_at, now),
        "meta_livraison_code": getattr(order, "meta_livraison_code", None),
    }


def _overdue_clause(cutoff: datetime):
    return and_(
        _no_tracking(),
        Order.status.in_(CONFIRMED_STATUSES),
        or_(
            Order.confirmed_at <= cutoff,
            and_(col(Order.confirmed_at).is_(None), Order.created_at <= cutoff),
        ),
    )


def _new_clause(cutoff: datetime):
    return and_(
        _no_tracking(),
        Order.status.in_(NEW_STATUSES),
        Order.created_at >= cutoff,
        or_(
            Order.status.notin_(CONFIRMED_STATUSES),
            and_(
                Order.status.in_(CONFIRMED_STATUSES),
                or_(
                    Order.confirmed_at > cutoff,
                    and_(col(Order.confirmed_at).is_(None), Order.created_at > cutoff),
                ),
            ),
        ),
    )


def _count(session: Session, clause) -> int:
    raw = session.exec(select(func.count(Order.id)).where(clause)).one()
    if isinstance(raw, (tuple, list)):
        return int(raw[0] or 0)
    return int(raw or 0)


def undispatched_summary(session: Session) -> dict:
    now = _now()
    cutoff = now - timedelta(hours=24)
    overdue_where = _overdue_clause(cutoff)
    new_where = _new_clause(cutoff)

    new_count = _count(session, new_where)
    overdue_count = _count(session, overdue_where)

    new_rows = session.exec(
        select(Order).where(new_where).order_by(col(Order.created_at).desc()).limit(ITEM_LIMIT)
    ).all()
    overdue_rows = session.exec(
        select(Order).where(overdue_where).order_by(col(Order.confirmed_at).asc(), col(Order.created_at).asc()).limit(ITEM_LIMIT)
    ).all()

    overdue_items = [
        dump_undispatched_item(row, now, row.confirmed_at or row.created_at) for row in overdue_rows
    ]
    new_items = [dump_undispatched_item(row, now, row.created_at) for row in new_rows]
    return {
        "new_orders_count": new_count,
        "overdue_orders_count": overdue_count,
        "total_count": new_count + overdue_count,
        "new_items": new_items,
        "overdue_items": overdue_items,
        "items": overdue_items,
    }
