"""Routing/delivery engine:

Два режима:
  1. `route_event_via_rules` — TG-only: совпадение по правилу
     (event_type × optional branch_filter) → telegram_group [× topic]
  2. `deliver_explicit` — модуль явно указывает channel_kind + recipients
     (для email — emails / employee_ids / branch_ids; для TG — chat_ids /
     telegram_group_ids)

Дедуп через `dedup_key` — 24-часовое окно по статусу `sent`.
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


def _lookup_or_create_event_type(db, EventType, event_type_key: str, source_module: str):
    et = EventType.query.filter_by(key=event_type_key).first()
    if et is None:
        et = EventType(key=event_type_key, label=event_type_key,
                       source_module=source_module)
        db.session.add(et)
        db.session.flush()
    return et


def _dedup_already_sent(Message, company_id: int, dedup_key: str) -> bool:
    """True если в последние 24ч уже было sent-сообщение с этим dedup_key."""
    if not dedup_key:
        return False
    recent = (Message.query
              .filter(Message.company_id == company_id,
                      Message.dedup_key == dedup_key,
                      Message.status == "sent",
                      Message.created_at >= datetime.utcnow() - timedelta(hours=24))
              .first())
    return recent is not None


def _resolve_email_recipients(recipients: dict, core_client) -> list[str]:
    """recipients.emails + employee_ids + branch_ids → плоский список email
    с дедупом сохраняющим порядок."""
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
    seen, uniq = set(), []
    for e in out:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def _resolve_telegram_chat_ids(recipients: dict, company_id: int,
                               TelegramGroup) -> list[int]:
    """Для deliver_explicit: chat_ids + telegram_group_ids → список chat_id."""
    out: list[int] = []
    for cid in recipients.get("chat_ids") or []:
        try:
            out.append(int(cid))
        except (TypeError, ValueError):
            continue
    group_ids = [int(g) for g in (recipients.get("telegram_group_ids") or [])]
    if group_ids:
        rows = (TelegramGroup.query
                .filter(TelegramGroup.company_id == company_id,
                        TelegramGroup.id.in_(group_ids))
                .all())
        for g in rows:
            out.append(g.chat_id)
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


# ── route_event_via_rules ──────────────────────────────────────────────────

def route_event_via_rules(
    *,
    db,
    Channel, RoutingRule, EventType, Message, TelegramGroup, TelegramTopic,
    company_id: int,
    source_module: str,
    event_type_key: str,
    branch_id: int | None,
    subject: str | None,
    body_text: str | None,
    body_html: str | None,
    payload: dict | None,
    dedup_key: str | None,
) -> dict:
    """TG-доставка по правилам.

    Возвращает {message_ids, skipped_reason?} или {error}.
    Транзакция — одна.
    """
    et = _lookup_or_create_event_type(db, EventType, event_type_key, source_module)

    # Канал-TG компании (один на компанию)
    ch = Channel.query.filter_by(company_id=company_id, kind="telegram",
                                 is_enabled=True).first()
    if ch is None:
        db.session.commit()  # сохраняем auto-created event_type
        return {"error": "telegram channel not configured for company",
                "message_ids": []}

    # Выбираем подходящие правила
    rules_query = (RoutingRule.query
                   .filter(RoutingRule.company_id == company_id,
                           RoutingRule.event_type_id == et.id,
                           RoutingRule.is_enabled.is_(True)))
    if branch_id is not None:
        from sqlalchemy import or_
        rules_query = rules_query.filter(
            or_(RoutingRule.branch_id.is_(None),
                RoutingRule.branch_id == int(branch_id)))
    else:
        rules_query = rules_query.filter(RoutingRule.branch_id.is_(None))
    rules = (rules_query
             .order_by(RoutingRule.priority.asc(), RoutingRule.id.asc())
             .all())
    if not rules:
        db.session.commit()
        return {"message_ids": [], "skipped_reason": "no_rules"}

    if _dedup_already_sent(Message, company_id, dedup_key):
        db.session.commit()
        return {"message_ids": [], "skipped_reason": "dedup_sent_recently"}

    if not subject:
        subject, body_text = _format_body(et.label, payload or {})

    created_ids: list[int] = []
    for rule in rules:
        group = TelegramGroup.query.get(rule.telegram_group_id)
        if group is None or group.archived_at is not None:
            continue
        thread_id = None
        if rule.topic_id:
            topic = TelegramTopic.query.get(rule.topic_id)
            if topic and topic.archived_at is None:
                thread_id = topic.telegram_thread_id

        msg_payload = dict(payload or {})
        if thread_id is not None:
            msg_payload["message_thread_id"] = thread_id

        m = Message(
            company_id=company_id, channel_id=ch.id,
            source_module=source_module, event_type=event_type_key,
            payload=msg_payload, to_address=str(group.chat_id),
            subject=subject or et.label,
            body_text=body_text or "",
            body_html=body_html,
            status="pending", dedup_key=dedup_key,
        )
        db.session.add(m)
        db.session.flush()
        created_ids.append(m.id)

    db.session.commit()
    return {"message_ids": created_ids}


# ── deliver_explicit ───────────────────────────────────────────────────────

def deliver_explicit(
    *,
    db, core_client,
    Channel, EventType, Message, TelegramGroup,
    company_id: int,
    source_module: str,
    event_type_key: str,
    channel_kind: str,
    recipients: dict,
    subject: str | None,
    body_text: str | None,
    body_html: str | None,
    payload: dict | None,
    parse_mode: str | None,
    dedup_key: str | None,
) -> dict:
    """Прямая доставка с явным списком получателей."""
    if channel_kind not in ("email", "telegram"):
        return {"error": f"unknown channel_kind={channel_kind!r}", "message_ids": []}

    # event_type — только для каталога/Журнала, не для роутинга
    _lookup_or_create_event_type(db, EventType, event_type_key, source_module)

    ch = Channel.query.filter_by(company_id=company_id, kind=channel_kind,
                                 is_enabled=True).first()
    if ch is None:
        db.session.commit()
        return {"error": f"channel {channel_kind} not configured for company",
                "message_ids": []}

    if _dedup_already_sent(Message, company_id, dedup_key):
        db.session.commit()
        return {"message_ids": [], "skipped_reason": "dedup_sent_recently"}

    created_ids: list[int] = []
    msg_payload_base = dict(payload or {})
    if parse_mode:
        msg_payload_base["parse_mode"] = parse_mode

    if channel_kind == "email":
        addrs = _resolve_email_recipients(recipients or {}, core_client)
        if not addrs:
            db.session.commit()
            return {"message_ids": [], "skipped_reason": "no_email_recipients"}
        for to_addr in addrs:
            m = Message(
                company_id=company_id, channel_id=ch.id,
                source_module=source_module, event_type=event_type_key,
                payload=msg_payload_base, to_address=to_addr,
                subject=subject or "(без темы)",
                body_text=body_text or "",
                body_html=body_html,
                status="pending", dedup_key=dedup_key,
            )
            db.session.add(m)
            db.session.flush()
            created_ids.append(m.id)
    else:  # telegram
        chat_ids = _resolve_telegram_chat_ids(recipients or {}, company_id, TelegramGroup)
        if not chat_ids:
            db.session.commit()
            return {"message_ids": [], "skipped_reason": "no_telegram_recipients"}
        for chat_id in chat_ids:
            m = Message(
                company_id=company_id, channel_id=ch.id,
                source_module=source_module, event_type=event_type_key,
                payload=msg_payload_base, to_address=str(chat_id),
                subject=subject, body_text=body_text or "",
                body_html=body_html,
                status="pending", dedup_key=dedup_key,
            )
            db.session.add(m)
            db.session.flush()
            created_ids.append(m.id)

    db.session.commit()
    return {"message_ids": created_ids}
