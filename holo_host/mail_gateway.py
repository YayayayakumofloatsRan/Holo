from __future__ import annotations

import imaplib
import json
import re
import smtplib
import tempfile
from abc import ABC, abstractmethod
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, make_msgid, parseaddr
from pathlib import Path
from typing import Iterable

from .common import compact_text, ensure_directory, stable_digest, utc_now
from .config import HostConfig, mail_password
from .models import IncomingMessage, OutgoingMessage


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        tmp_path = Path(handle.name)
        handle.write(text)
    try:
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _strip_html(html: str) -> str:
    cleaned = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    cleaned = re.sub(r"</p>", "\n\n", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return " ".join(cleaned.split())


def _extract_body(message: EmailMessage) -> tuple[str, str]:
    if message.is_multipart():
        text_parts: list[str] = []
        html_parts: list[str] = []
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = str(part.get_content_disposition() or "")
            if disposition == "attachment":
                continue
            try:
                payload = part.get_content()
            except Exception:
                continue
            if content_type == "text/plain":
                text_parts.append(str(payload))
            elif content_type == "text/html":
                html_parts.append(str(payload))
        body_text = "\n\n".join(part.strip() for part in text_parts if part.strip())
        body_html = "\n".join(part.strip() for part in html_parts if part.strip())
    else:
        payload = str(message.get_content())
        if message.get_content_type() == "text/html":
            body_text = _strip_html(payload)
            body_html = payload
        else:
            body_text = payload
            body_html = ""

    if not body_text and body_html:
        body_text = _strip_html(body_html)
    return body_text.strip(), body_html.strip()


def _split_references(header_value: str | None) -> list[str]:
    if not header_value:
        return []
    return [item.strip() for item in header_value.split() if item.strip()]


def _thread_key(message_id: str, in_reply_to: str, references: Iterable[str], subject: str) -> str:
    refs = [item for item in references if item]
    if refs:
        return refs[0]
    if in_reply_to:
        return in_reply_to
    if message_id:
        return message_id
    return f"subject:{stable_digest(subject)}"


def _reply_subject(subject: str) -> str:
    if not subject:
        return "Re: (no subject)"
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"


class MailGateway(ABC):
    @abstractmethod
    def poll_inbox(self, limit: int) -> list[IncomingMessage]:
        raise NotImplementedError

    @abstractmethod
    def acknowledge(self, message: IncomingMessage) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_reply(self, outgoing: OutgoingMessage) -> str:
        raise NotImplementedError


class MaildirGateway(MailGateway):
    def __init__(self, config: HostConfig):
        self.inbox_dir = ensure_directory(config.mail.maildir_inbox)
        self.processed_dir = ensure_directory(config.mail.maildir_processed)
        self.outbox_dir = ensure_directory(config.mail.maildir_outbox)

    def poll_inbox(self, limit: int) -> list[IncomingMessage]:
        messages: list[IncomingMessage] = []
        for path in sorted(self.inbox_dir.iterdir())[:limit]:
            if path.is_dir():
                continue
            message = self._load_path(path)
            if message:
                messages.append(message)
        return messages

    def _load_path(self, path: Path) -> IncomingMessage | None:
        if path.suffix.lower() == ".json":
            try:
                raw_text = path.read_text(encoding="utf-8")
                payload = json.loads(raw_text)
            except (OSError, ValueError, json.JSONDecodeError):
                return None
            message_id = str(payload.get("message_id") or stable_digest(path.name, raw_text))
            references = list(payload.get("references", []))
            in_reply_to = str(payload.get("in_reply_to", ""))
            sender_email = str(payload.get("sender_email") or payload.get("from") or "").strip()
            return IncomingMessage(
                message_id=message_id,
                thread_key=str(payload.get("thread_key") or _thread_key(message_id, in_reply_to, references, str(payload.get("subject", "")))),
                subject=str(payload.get("subject", "")),
                sender_email=sender_email,
                sender_name=str(payload.get("sender_name", "")),
                reply_to_email=str(payload.get("reply_to_email", sender_email)),
                in_reply_to=in_reply_to,
                references=references,
                body_text=str(payload.get("body_text", "")),
                body_html=str(payload.get("body_html", "")),
                received_at=str(payload.get("received_at", utc_now())),
                source_ref=str(path),
                metadata={"maildir_path": str(path), "maildir_format": "json"},
            )
        try:
            raw = path.read_bytes()
            parsed = BytesParser(policy=policy.default).parsebytes(raw)
        except (OSError, ValueError):
            return None
        sender_name, sender_email = parseaddr(str(parsed.get("from", "")))
        reply_to_name, reply_to_email = parseaddr(str(parsed.get("reply-to", "")))
        body_text, body_html = _extract_body(parsed)
        message_id = str(parsed.get("message-id") or f"<maildir-{stable_digest(path.name, compact_text(body_text, 64))}@holo.local>")
        references = _split_references(parsed.get("references"))
        in_reply_to = str(parsed.get("in-reply-to") or "")
        return IncomingMessage(
            message_id=message_id,
            thread_key=_thread_key(message_id, in_reply_to, references, _decode_header(parsed.get("subject"))),
            subject=_decode_header(parsed.get("subject")),
            sender_email=sender_email,
            sender_name=sender_name,
            reply_to_email=reply_to_email or sender_email,
            in_reply_to=in_reply_to,
            references=references,
            body_text=body_text,
            body_html=body_html,
            received_at=utc_now(),
            source_ref=str(path),
            metadata={"maildir_path": str(path), "maildir_format": "eml", "reply_to_name": reply_to_name},
        )

    def acknowledge(self, message: IncomingMessage) -> None:
        if not message.source_ref:
            return
        source = Path(message.source_ref)
        if not source.exists():
            return
        target = self.processed_dir / source.name
        if target.exists():
            target = self.processed_dir / f"{stable_digest(source.name, utc_now())}-{source.name}"
        source.replace(target)

    def send_reply(self, outgoing: OutgoingMessage) -> str:
        remote_message_id = make_msgid(domain="holo.local")
        payload = {
            "message_id": remote_message_id,
            "recipient_email": outgoing.recipient_email,
            "recipient_name": outgoing.recipient_name,
            "subject": outgoing.subject,
            "body_text": outgoing.body_text,
            "body_html": outgoing.body_html,
            "thread_key": outgoing.thread_key,
            "in_reply_to": outgoing.in_reply_to,
            "references": outgoing.references,
            "metadata": outgoing.metadata,
            "created_at": utc_now(),
        }
        target = self.outbox_dir / f"{stable_digest(outgoing.recipient_email, outgoing.subject, utc_now())}.json"
        atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2))
        return remote_message_id


class ImapSmtpGateway(MailGateway):
    def __init__(self, config: HostConfig):
        self.config = config

    def _imap(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.config.mail.imap_host, self.config.mail.imap_port)
        conn.login(self.config.mail.username, mail_password(self.config))
        conn.select(self.config.mail.mailbox)
        return conn

    def poll_inbox(self, limit: int) -> list[IncomingMessage]:
        conn = self._imap()
        try:
            status, data = conn.uid("search", None, "UNSEEN")
            if status != "OK":
                return []
            uids = [item for item in data[0].split() if item][-limit:]
            messages: list[IncomingMessage] = []
            for uid in uids:
                status, payload = conn.uid("fetch", uid, "(BODY.PEEK[])")
                if status != "OK" or not payload:
                    continue
                raw = b""
                for item in payload:
                    if isinstance(item, tuple):
                        raw = item[1]
                        break
                if not raw:
                    continue
                parsed = BytesParser(policy=policy.default).parsebytes(raw)
                sender_name, sender_email = parseaddr(str(parsed.get("from", "")))
                reply_to_name, reply_to_email = parseaddr(str(parsed.get("reply-to", "")))
                body_text, body_html = _extract_body(parsed)
                message_id = str(parsed.get("message-id") or f"<imap-{uid.decode()}@holo.local>")
                references = _split_references(parsed.get("references"))
                in_reply_to = str(parsed.get("in-reply-to") or "")
                messages.append(
                    IncomingMessage(
                        message_id=message_id,
                        thread_key=_thread_key(message_id, in_reply_to, references, _decode_header(parsed.get("subject"))),
                        subject=_decode_header(parsed.get("subject")),
                        sender_email=sender_email,
                        sender_name=sender_name,
                        reply_to_email=reply_to_email or sender_email,
                        in_reply_to=in_reply_to,
                        references=references,
                        body_text=body_text,
                        body_html=body_html,
                        received_at=utc_now(),
                        source_ref=uid.decode(),
                        metadata={"imap_uid": uid.decode(), "reply_to_name": reply_to_name},
                    )
                )
            return messages
        finally:
            conn.close()
            conn.logout()

    def acknowledge(self, message: IncomingMessage) -> None:
        if not self.config.mail.mark_seen_after_fetch or not message.source_ref:
            return
        conn = self._imap()
        try:
            conn.uid("store", message.source_ref, "+FLAGS", "(\\Seen)")
        finally:
            conn.close()
            conn.logout()

    def send_reply(self, outgoing: OutgoingMessage) -> str:
        email_message = EmailMessage()
        sent_from = self.config.mail.sent_from or self.config.mail.username
        email_message["From"] = sent_from
        email_message["To"] = formataddr((outgoing.recipient_name, outgoing.recipient_email))
        email_message["Subject"] = _reply_subject(outgoing.subject)
        if outgoing.in_reply_to:
            email_message["In-Reply-To"] = outgoing.in_reply_to
        references = [item for item in outgoing.references if item]
        if outgoing.in_reply_to and outgoing.in_reply_to not in references:
            references.append(outgoing.in_reply_to)
        if references:
            email_message["References"] = " ".join(references)
        remote_message_id = make_msgid()
        email_message["Message-ID"] = remote_message_id
        email_message.set_content(outgoing.body_text)
        if outgoing.body_html:
            email_message.add_alternative(outgoing.body_html, subtype="html")

        with smtplib.SMTP(self.config.mail.smtp_host, self.config.mail.smtp_port, timeout=30) as conn:
            conn.starttls()
            conn.login(self.config.mail.username, mail_password(self.config))
            conn.send_message(email_message)
        return remote_message_id


def build_mail_gateway(config: HostConfig) -> MailGateway:
    if config.mail.transport == "imap_smtp":
        return ImapSmtpGateway(config)
    return MaildirGateway(config)
