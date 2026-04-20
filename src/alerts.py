"""
Sistema de alertas: compara snapshot actual vs snapshot anterior y detecta
eventos relevantes para la decisión de inversión.

Triggers configurables:
1. Empresa entra en Hunting Ground (composite≥7.5 + EV/FCF≤20)
2. IRR asymmetry mejora significativamente (best>20% AND worst>-5%)
3. Composite rating sube ≥0.5 puntos
4. EV/FCF cae ≥20% en una empresa Top Tier
5. Best IRR cruza el 25%
6. Empresa nueva entra al Top Tier (composite≥7.5 desde abajo)

Output: docs/data/alerts.json con la lista de eventos activos.
El frontend muestra una banda en el header con los alerts más recientes.

Notificación external (opcional, vía GitHub Actions secret):
- Telegram bot: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
- Discord webhook: DISCORD_WEBHOOK_URL
- Email: configurable via SMTP secrets
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

# Umbrales para alertas
HUNTING_GROUND_COMPOSITE = 7.5
HUNTING_GROUND_EV_FCF = 20.0
IRR_BEST_HIGH = 0.20         # Best IRR > 20%
IRR_WORST_FLOOR = -0.05      # Worst IRR > -5%
COMPOSITE_DELTA_THRESHOLD = 0.5
EV_FCF_DROP_THRESHOLD = 0.20  # 20% caída
BEST_IRR_CROSS = 0.25         # Best IRR cruza 25%
TOP_TIER_THRESHOLD = 7.5

ALERT_SEVERITIES = {
    "hunting_ground_entry": "high",
    "asymmetry_improved": "high",
    "composite_upgrade": "medium",
    "ev_fcf_drop": "medium",
    "best_irr_crossed_25": "high",
    "new_top_tier": "high",
    "composite_downgrade": "medium",
    "exited_hunting": "low",
}


def _build_index(df: pd.DataFrame) -> dict[str, dict]:
    """Indexa por ticker para acceso rápido."""
    return {row["ticker"]: row.to_dict() for _, row in df.iterrows()}


def _is_hunting(rec: dict) -> bool:
    if rec.get("rating_composite") is None or rec.get("ev_fcf") is None:
        return False
    return (
        rec["rating_composite"] >= HUNTING_GROUND_COMPOSITE
        and 0 < rec["ev_fcf"] <= HUNTING_GROUND_EV_FCF
    )


def _has_good_asymmetry(rec: dict) -> bool:
    if rec.get("irr_best") is None or rec.get("irr_worst") is None:
        return False
    return rec["irr_best"] > IRR_BEST_HIGH and rec["irr_worst"] > IRR_WORST_FLOOR


def detect_alerts(
    current: pd.DataFrame, previous: pd.DataFrame | None
) -> list[dict[str, Any]]:
    """
    Compara dos snapshots y devuelve lista de eventos.
    Si previous=None, solo detecta condiciones absolutas (no transiciones).
    """
    alerts = []
    curr_idx = _build_index(current)
    prev_idx = _build_index(previous) if previous is not None and not previous.empty else {}

    for ticker, c in curr_idx.items():
        p = prev_idx.get(ticker)

        # 1. Hunting Ground entry (transition o estado actual si no hay snapshot previo)
        is_hunt_now = _is_hunting(c)
        was_hunt_before = _is_hunting(p) if p else None
        if is_hunt_now and was_hunt_before is False:
            alerts.append({
                "type": "hunting_ground_entry",
                "severity": ALERT_SEVERITIES["hunting_ground_entry"],
                "ticker": ticker,
                "name": c.get("name", ticker),
                "category": c.get("category"),
                "message": f"{ticker} entered Hunting Ground (rating {c['rating_composite']:.2f}, EV/FCF {c['ev_fcf']:.1f}x)",
                "metrics": {
                    "rating_composite": c["rating_composite"],
                    "ev_fcf": c["ev_fcf"],
                    "irr_best": c.get("irr_best"),
                },
            })
        elif is_hunt_now and was_hunt_before is None:
            # No previous snapshot: emit as "current state" alert (low severity)
            alerts.append({
                "type": "hunting_ground_current",
                "severity": "low",
                "ticker": ticker,
                "name": c.get("name", ticker),
                "category": c.get("category"),
                "message": f"{ticker} currently in Hunting Ground (rating {c['rating_composite']:.2f}, EV/FCF {c['ev_fcf']:.1f}x)",
                "metrics": {
                    "rating_composite": c["rating_composite"],
                    "ev_fcf": c["ev_fcf"],
                },
            })
        elif not is_hunt_now and was_hunt_before is True:
            alerts.append({
                "type": "exited_hunting",
                "severity": ALERT_SEVERITIES["exited_hunting"],
                "ticker": ticker,
                "name": c.get("name", ticker),
                "category": c.get("category"),
                "message": f"{ticker} exited Hunting Ground",
                "metrics": {
                    "rating_composite": c["rating_composite"],
                    "ev_fcf": c["ev_fcf"],
                },
            })

        # 2. Good IRR asymmetry
        if _has_good_asymmetry(c):
            was_good = _has_good_asymmetry(p) if p else False
            if not was_good:
                alerts.append({
                    "type": "asymmetry_improved",
                    "severity": ALERT_SEVERITIES["asymmetry_improved"],
                    "ticker": ticker,
                    "name": c.get("name", ticker),
                    "category": c.get("category"),
                    "message": f"{ticker} now has favorable IRR asymmetry (best {c['irr_best']*100:.1f}%, worst {c['irr_worst']*100:.1f}%)",
                    "metrics": {
                        "irr_best": c["irr_best"],
                        "irr_worst": c["irr_worst"],
                        "irr_asymmetry_ratio": c.get("irr_asymmetry_ratio"),
                    },
                })

        # 3. Composite rating upgrade
        if p and c.get("rating_composite") is not None and p.get("rating_composite") is not None:
            delta = c["rating_composite"] - p["rating_composite"]
            if delta >= COMPOSITE_DELTA_THRESHOLD:
                alerts.append({
                    "type": "composite_upgrade",
                    "severity": ALERT_SEVERITIES["composite_upgrade"],
                    "ticker": ticker,
                    "name": c.get("name", ticker),
                    "category": c.get("category"),
                    "message": f"{ticker} composite upgraded {p['rating_composite']:.2f} → {c['rating_composite']:.2f} (+{delta:.2f})",
                    "metrics": {
                        "from": p["rating_composite"],
                        "to": c["rating_composite"],
                        "delta": delta,
                    },
                })
            elif delta <= -COMPOSITE_DELTA_THRESHOLD:
                alerts.append({
                    "type": "composite_downgrade",
                    "severity": ALERT_SEVERITIES["composite_downgrade"],
                    "ticker": ticker,
                    "name": c.get("name", ticker),
                    "category": c.get("category"),
                    "message": f"{ticker} composite downgraded {p['rating_composite']:.2f} → {c['rating_composite']:.2f} ({delta:.2f})",
                    "metrics": {
                        "from": p["rating_composite"],
                        "to": c["rating_composite"],
                        "delta": delta,
                    },
                })

        # 4. EV/FCF drop ≥20% en empresas Top Tier
        if (p and c.get("ev_fcf") and p.get("ev_fcf")
                and c["ev_fcf"] > 0 and p["ev_fcf"] > 0
                and c.get("rating_composite", 0) >= TOP_TIER_THRESHOLD):
            drop = (p["ev_fcf"] - c["ev_fcf"]) / p["ev_fcf"]
            if drop >= EV_FCF_DROP_THRESHOLD:
                alerts.append({
                    "type": "ev_fcf_drop",
                    "severity": ALERT_SEVERITIES["ev_fcf_drop"],
                    "ticker": ticker,
                    "name": c.get("name", ticker),
                    "category": c.get("category"),
                    "message": f"{ticker} (Top Tier) EV/FCF dropped {drop*100:.0f}%: {p['ev_fcf']:.1f}x → {c['ev_fcf']:.1f}x",
                    "metrics": {
                        "from": p["ev_fcf"],
                        "to": c["ev_fcf"],
                        "drop_pct": drop,
                        "rating_composite": c["rating_composite"],
                    },
                })

        # 5. Best IRR cruza 25% al alza
        if p and c.get("irr_best") is not None and p.get("irr_best") is not None:
            if p["irr_best"] < BEST_IRR_CROSS <= c["irr_best"]:
                alerts.append({
                    "type": "best_irr_crossed_25",
                    "severity": ALERT_SEVERITIES["best_irr_crossed_25"],
                    "ticker": ticker,
                    "name": c.get("name", ticker),
                    "category": c.get("category"),
                    "message": f"{ticker} Best IRR crossed 25% ({p['irr_best']*100:.1f}% → {c['irr_best']*100:.1f}%)",
                    "metrics": {
                        "from": p["irr_best"],
                        "to": c["irr_best"],
                    },
                })

        # 6. Nueva entrada al Top Tier
        if p and c.get("rating_composite") and p.get("rating_composite"):
            if p["rating_composite"] < TOP_TIER_THRESHOLD <= c["rating_composite"]:
                alerts.append({
                    "type": "new_top_tier",
                    "severity": ALERT_SEVERITIES["new_top_tier"],
                    "ticker": ticker,
                    "name": c.get("name", ticker),
                    "category": c.get("category"),
                    "message": f"{ticker} promoted to Top Tier ({p['rating_composite']:.2f} → {c['rating_composite']:.2f})",
                    "metrics": {
                        "from": p["rating_composite"],
                        "to": c["rating_composite"],
                    },
                })

    # Ordenar por severidad luego por ticker
    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (severity_order.get(a["severity"], 3), a["ticker"]))
    return alerts


def write_alerts_json(
    alerts: list[dict],
    output_path: str | Path = "docs/data/alerts.json",
) -> None:
    """Escribe el JSON consumible por el frontend."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_alerts": len(alerts),
            "by_severity": {
                "high": sum(1 for a in alerts if a["severity"] == "high"),
                "medium": sum(1 for a in alerts if a["severity"] == "medium"),
                "low": sum(1 for a in alerts if a["severity"] == "low"),
            },
        },
        "alerts": alerts,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    log.info("✅ Alerts → %s (%d alerts)", output_path, len(alerts))


# ============================================================================
# NOTIFICATIONS — opcional, solo si se configuran las env vars
# ============================================================================

def _format_alerts_text(alerts: list[dict], max_items: int = 15) -> tuple[str, str]:
    """
    Construye el texto plano y HTML para emails.
    Devuelve (text_plain, html).
    """
    high_alerts = [a for a in alerts if a["severity"] == "high"]
    medium_alerts = [a for a in alerts if a["severity"] == "medium"]

    icons = {
        "hunting_ground_entry": "🎯",
        "hunting_ground_current": "🎯",
        "asymmetry_improved": "📈",
        "best_irr_crossed_25": "🚀",
        "new_top_tier": "⭐",
        "composite_upgrade": "▲",
        "composite_downgrade": "▼",
        "ev_fcf_drop": "💰",
        "exited_hunting": "↗",
    }

    # Plain text
    lines = ["WATCHLIST ALERTS", "=" * 50, ""]
    if high_alerts:
        lines.append(f"HIGH PRIORITY ({len(high_alerts)}):")
        for a in high_alerts[:max_items]:
            icon = icons.get(a["type"], "•")
            lines.append(f"  {icon} {a['ticker']:8s} — {a['message']}")
        lines.append("")
    if medium_alerts:
        lines.append(f"MEDIUM PRIORITY ({len(medium_alerts)}):")
        for a in medium_alerts[: max(0, max_items - len(high_alerts))]:
            icon = icons.get(a["type"], "•")
            lines.append(f"  {icon} {a['ticker']:8s} — {a['message']}")
        lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    text_plain = "\n".join(lines)

    # HTML
    sev_colors = {"high": "#c77d46", "medium": "#6b80a8", "low": "#7a8579"}
    html_parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<style>',
        'body { font-family: -apple-system, system-ui, sans-serif; background: #0a0b0d; color: #e8e6e0; padding: 24px; }',
        '.container { max-width: 600px; margin: 0 auto; }',
        'h1 { font-size: 18px; letter-spacing: -0.02em; color: #c77d46; border-bottom: 1px solid #2a2d34; padding-bottom: 8px; }',
        '.alert { padding: 12px; margin: 8px 0; border-left: 3px solid; background: #121317; border-radius: 2px; }',
        '.alert.high { border-color: #c77d46; }',
        '.alert.medium { border-color: #6b80a8; }',
        '.ticker { font-weight: 600; color: #c77d46; font-family: monospace; }',
        '.category { color: #6b6761; font-size: 11px; margin-left: 8px; }',
        '.message { color: #e8e6e0; margin-top: 4px; font-size: 14px; }',
        '.footer { color: #4a4743; font-size: 11px; margin-top: 24px; padding-top: 12px; border-top: 1px solid #2a2d34; }',
        '</style></head><body><div class="container">',
        '<h1>Watchlist Alerts</h1>',
    ]
    if not (high_alerts or medium_alerts):
        html_parts.append('<p style="color:#6b6761;">No high/medium priority alerts in this snapshot.</p>')
    for a in (high_alerts + medium_alerts)[:max_items]:
        icon = icons.get(a["type"], "•")
        html_parts.append(
            f'<div class="alert {a["severity"]}">'
            f'<span class="ticker">{icon} {a["ticker"]}</span>'
            f'<span class="category">{a.get("category", "")}</span>'
            f'<div class="message">{a["message"]}</div>'
            f'</div>'
        )
    html_parts.append(f'<div class="footer">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</div>')
    html_parts.append('</div></body></html>')
    html = "\n".join(html_parts)

    return text_plain, html


def notify_email(alerts: list[dict]) -> bool:
    """
    Envía email con resumen de alertas usando SMTP.

    Variables de entorno requeridas (configurables como GitHub Secrets):
    - SMTP_HOST           ej: smtp.gmail.com
    - SMTP_PORT           ej: 587 (TLS) o 465 (SSL)
    - SMTP_USER           email del remitente
    - SMTP_PASSWORD       app password (NO la contraseña real)
    - EMAIL_TO            destinatario (puede ser el mismo que SMTP_USER)

    Solo envía si hay al menos 1 alerta high o medium.
    """
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    to_addr = os.environ.get("EMAIL_TO") or user

    if not all([host, user, password, to_addr]):
        log.info("Email no configurado (faltan SMTP_HOST/USER/PASSWORD/EMAIL_TO)")
        return False

    relevant = [a for a in alerts if a["severity"] in ("high", "medium")]
    if not relevant:
        log.info("No hay alertas relevantes para email")
        return False

    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    text_plain, html = _format_alerts_text(alerts)
    n_high = sum(1 for a in alerts if a["severity"] == "high")
    n_med = sum(1 for a in alerts if a["severity"] == "medium")
    subject = f"📊 Watchlist: {n_high} high · {n_med} medium alerts"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(text_plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())
        server.quit()
        log.info("✅ Email enviado a %s (%d alerts)", to_addr, len(relevant))
        return True
    except Exception as e:
        log.error("❌ Error enviando email: %s", e)
        return False


def notify_whatsapp(alerts: list[dict]) -> bool:
    """
    Envía mensaje WhatsApp vía CallMeBot (gratuito, no requiere infra).

    Setup (one-time):
    1. Añade el contacto +34 644 67 38 13 a tu agenda como "CallMeBot"
    2. Envía un WhatsApp a ese número con el texto: "I allow callmebot to send me messages"
    3. Recibirás un código tipo "1234567" — esa es tu API key
    4. Configura GitHub Secrets:
       - WHATSAPP_PHONE      tu número con código país (ej: 34666123456, sin + ni espacios)
       - WHATSAPP_API_KEY    el código que recibiste

    Solo envía las HIGH severity para no spamear.
    Limitaciones: 5 mensajes/min, plain text only.
    """
    phone = os.environ.get("WHATSAPP_PHONE")
    api_key = os.environ.get("WHATSAPP_API_KEY")
    if not phone or not api_key:
        log.info("WhatsApp no configurado (faltan WHATSAPP_PHONE/API_KEY)")
        return False

    high_alerts = [a for a in alerts if a["severity"] == "high"]
    if not high_alerts:
        log.info("No hay alertas high para WhatsApp")
        return False

    icons = {
        "hunting_ground_entry": "🎯",
        "asymmetry_improved": "📈",
        "best_irr_crossed_25": "🚀",
        "new_top_tier": "⭐",
    }

    # WhatsApp/CallMeBot tiene límite de tamaño; resumen muy compacto
    lines = [f"📊 Watchlist: {len(high_alerts)} high alerts"]
    for a in high_alerts[:8]:
        icon = icons.get(a["type"], "•")
        lines.append(f"{icon} {a['ticker']}: {a['message'][:80]}")
    if len(high_alerts) > 8:
        lines.append(f"... y {len(high_alerts) - 8} más en el dashboard")

    text = "\n".join(lines)

    import urllib.request
    import urllib.parse

    url = (
        f"https://api.callmebot.com/whatsapp.php?"
        f"phone={phone}&text={urllib.parse.quote(text)}&apikey={api_key}"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            if resp.status == 200 and "Message queued" in body or "Message Sent" in body or resp.status == 200:
                log.info("✅ WhatsApp enviado (%d alerts)", len(high_alerts))
                return True
            log.warning("WhatsApp respuesta inesperada: %s — %s", resp.status, body[:200])
            return False
    except Exception as e:
        log.error("❌ Error WhatsApp: %s", e)
        return False


def main():
    """Pipeline standalone: lee snapshots y escribe alerts.json"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    snapshots_dir = Path("data/snapshots")
    current_path = Path("docs/data/watchlist.json")
    if not current_path.exists():
        log.error("No existe %s — corre `make build` primero", current_path)
        return

    with open(current_path) as f:
        current_data = json.load(f)
    current_df = pd.DataFrame(current_data["companies"])

    # Encuentra el snapshot anterior (si existe)
    previous_df = None
    if snapshots_dir.exists():
        snapshots = sorted(snapshots_dir.glob("*_watchlist.json"))
        if snapshots:
            with open(snapshots[-1]) as f:
                prev_data = json.load(f)
            previous_df = pd.DataFrame(prev_data.get("companies", []))
            log.info("Snapshot previo: %s", snapshots[-1].name)

    alerts = detect_alerts(current_df, previous_df)
    write_alerts_json(alerts)

    # Notificaciones (silentes si no hay credenciales configuradas)
    notify_email(alerts)
    notify_whatsapp(alerts)


if __name__ == "__main__":
    main()
