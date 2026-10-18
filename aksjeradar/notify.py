"""
Varsling: Telegram og e-post. Begge leser innstillinger fra .env (se .env.example).

Telegram:  TELEGRAM_BOT_TOKEN og TELEGRAM_CHAT_ID
E-post:    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

log = logging.getLogger("aksjeradar.notify")


def _split(text: str, limit: int = 3900) -> list[str]:
    """Telegram tillater maks 4096 tegn per melding – del opp på linjeskift."""
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    return chunks


def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.info("Telegram er ikke satt opp (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID mangler i .env) – hopper over.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in _split(text):
        try:
            r = requests.post(
                url,
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=20,
            )
            if not r.ok:
                log.warning("Telegram svarte %s: %s", r.status_code, r.text[:200])
                return False
        except requests.RequestException as e:
            log.warning("Telegram feilet: %s", e)
            return False
    log.info("Telegram-melding sendt.")
    return True


def send_email(subject: str, html_body: str, text_body: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("EMAIL_FROM", user).strip()
    to = os.getenv("EMAIL_TO", "").strip()
    if not (host and user and password and to):
        log.info("E-post er ikke satt opp (SMTP_* / EMAIL_TO mangler i .env) – hopper over.")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(sender, [a.strip() for a in to.split(",")], msg.as_string())
        log.info("E-post sendt til %s.", to)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("E-post feilet: %s", e)
        return False
