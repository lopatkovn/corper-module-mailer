"""Routing engine: событие → правила → получатели → message(pending).

Вызывается из POST /events. Работает в контексте Flask app (db.session,
CoreClient).
"""
from datetime import datetime, timedelta
import json


def _format_body(event_label: str, payload: dict) -> tuple[str, str]:
    """Простой fallback-рендер subject/body — пока без Jinja-шаблонов.

    Шаблонизация — следующая фаза (доменные шаблоны на event_type).
    """
    subject = event_label or "Уведомление CORPER"
    lines = [subject, ""]
    for k, v in (payload or {}).items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        lines.append(f"{k}: {v}")
    body = "\n".join(lines)
    return subject, body


def _resolve_email_recipients(recipients: dict, core_client, company_id: int) -> list[str]:
    """recipients.emails + employee_ids + branch_ids → плоский список email."""
    out: list[str] = []
    for e in recipients.get("emails") or []:
        if e and "@" in e:
            out.append(e.strip())
    for eid in recipients.get("employee_ids") or []:
        try:
            emp = core_client.get_employee(int(eid))
            if emp and emp.get("email"):
                out.append(emp["email"])
        except Exception:
            continue
    for bid in recipients.get("branch_ids") or []:
        try:
            emps = core_client.get_branch_employees(int(bid)) or []
            for emp in emps:
                if emp.get("email"):
                    out.append(emp["email"])
        except Exception:
            continue
    # дедуп с сохранением порядка
    seen, uniq = set(), []
    for e in out:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def _resolve_telegram_chat_ids(recipients: dict, company_id: int, TelegramGroup) -> list[tuple[int, int]]:
    """recipients.telegram_group_ids → [(group_id, chat_id), ...].

    Возвращаются только группы где is_member=True и can_send=True (если знаем).
    """
    group_ids = recipients.get("telegram_group_ids") or []
    if not group_ids:
        return []
    rows = TelegramGroup.query.filter(
        TelegramGroup.company_id == company_id,
        TelegramGroup.id.in_([int(g) for g in group_ids]),
    ).all()
    return [(g.id, g.chat_id) for g in rows]


def route_event(
    *,
    db,
    core_client,
    Channel, RoutingRule, EventType, Message, TelegramGroup,
    company_id: int,
    source_module: str,
    event_type_key: str,
    payload: dict,
    branch_id: int | None = None,
    dedup_key: str | None = None,
) -> dict:
    """Главная функция. Возвращает {message_ids, skipped_reason?}.

    Транзакция — одна, на всё.
    """
    # 1) lookup или auto-create event_type (stub для незарегистрированных)
    et = EventType.query.filter_by(key=event_type_key).first()
    if et is None:
        et = EventType(
            key=event_type_key,
            label=event_type_key,
            source_module=source_module,
        )
        db.session.add(et)
        db.session.flush()

    # 2) выбор правил
    rules = (RoutingRule.query
             .filter(RoutingRule.company_id == company_id,
                     RoutingRule.event_type_id == et.id,
                     RoutingRule.is_enabled.is_(True))
             .order_by(RoutingRule.priority.asc(), RoutingRule.id.asc())
             .all())
    if not rules:
        return {"message_ids": [], "skipped_reason": "no_rules"}

    # 3) дедуп
    if dedup_key:
        recent = (Message.query
                  .filter(Message.company_id == company_id,
                          Message.dedup_key == dedup_key,
                          Message.status == "sent",
                          Message.created_at >= datetime.utcnow() - timedelta(hours=24))
                  .first())
        if recent:
            return {"message_ids": [], "skipped_reason": "dedup_sent_recently"}

    # 4) для каждого правила — материализуем сообщения
    subject, body_text = _format_body(et.label, payload)
    created_ids: list[int] = []

    for rule in rules:
        ch = Channel.query.get(rule.channel_id)
        if ch is None or not ch.is_enabled:
            continue
        recipients = rule.recipients or {}

        if ch.kind == "email":
            for to_addr in _resolve_email_recipients(recipients, core_client, company_id):
                m = Message(
                    company_id=company_id, channel_id=ch.id,
                    source_module=source_module, event_type=event_type_key,
                    payload=payload or {}, to_address=to_addr,
                    subject=subject, body_text=body_text,
                    status="pending", dedup_key=dedup_key,
                )
                db.session.add(m)
                db.session.flush()
                created_ids.append(m.id)

        elif ch.kind == "telegram":
            for _gid, chat_id in _resolve_telegram_chat_ids(recipients, company_id, TelegramGroup):
                m = Message(
                    company_id=company_id, channel_id=ch.id,
                    source_module=source_module, event_type=event_type_key,
                    payload=payload or {}, to_address=str(chat_id),
                    subject=subject, body_text=body_text,
                    status="pending", dedup_key=dedup_key,
                )
                db.session.add(m)
                db.session.flush()
                created_ids.append(m.id)

    db.session.commit()
    return {"message_ids": created_ids}
