"""Create Outlook drafts.

Windows + Outlook desktop + pywin32  -> real MailItems via COM (display / save as draft / send)
Anything else (or mode == "eml")      -> .eml files with the ``X-Unsent: 1`` header, which Outlook opens
                                         as an editable, unsent draft when double-clicked.

Safety: sending is OFF unless config.outlook.allow_send is true AND the request explicitly asks for it.
"""
from __future__ import annotations

import mimetypes
import sys
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

from .config import ROOT, load_config


def have_com() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in s)[:90].strip()


def write_eml(to: str, subject: str, html_body: str, attachments: list[Path], out_dir: Path, name: str | None = None) -> Path:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg["X-Unsent"] = "1"
    msg["Date"] = formatdate(localtime=True)
    msg.set_content("This message is best viewed in an HTML-capable mail client.")
    msg.add_alternative(html_body, subtype="html")
    for a in attachments:
        ctype = mimetypes.guess_type(a.name)[0] or "application/octet-stream"
        main, sub = ctype.split("/")
        msg.add_attachment(a.read_bytes(), maintype=main, subtype=sub, filename=a.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe(name or subject)
    p = out_dir / f"{stem}.eml"
    n = 1
    while p.exists():
        n += 1
        p = out_dir / f"{stem} ({n}).eml"
    p.write_bytes(bytes(msg))
    return p


def create_drafts(items: list[dict], mode: str, out_dir: Path) -> dict:
    """items: [{to, subject, html, attachments:[Path]}]. mode: display | draft | send | eml"""
    cfg = load_config()["outlook"]
    if mode == "send" and not cfg.get("allow_send"):
        raise PermissionError("Sending is disabled. Set outlook.allow_send=true in config.json to enable it.")
    results = []
    if mode != "eml" and have_com():
        import win32com.client
        app = win32com.client.Dispatch("Outlook.Application")
        for it in items:
            m = app.CreateItem(0)
            m.To = it["to"]
            m.Subject = it["subject"]
            m.HTMLBody = it["html"]
            if cfg.get("shared_mailbox"):
                m.SentOnBehalfOfName = cfg["shared_mailbox"]
            for a in it["attachments"]:
                m.Attachments.Add(str(a))
            if mode == "send":
                m.Send()
            elif mode == "draft":
                m.Save()
            else:
                m.Display(False)
            results.append({"subject": it["subject"], "to": it["to"], "via": f"outlook-{mode}"})
        return {"engine": "outlook", "mode": mode, "items": results}
    for it in items:
        p = write_eml(it["to"], it["subject"], it["html"], it["attachments"], out_dir, it.get("name"))
        results.append({"subject": it["subject"], "to": it["to"], "via": "eml", "file": str(p.relative_to(ROOT))})
    return {"engine": "eml", "mode": "eml", "items": results,
            "note": "Outlook COM not available here - wrote .eml drafts (double-click to open in Outlook)."}
