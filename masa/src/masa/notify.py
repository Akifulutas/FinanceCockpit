"""macOS Native Notification Bridge and System Alerts (İP-12).

Design Invariants:
1. Native macOS user notifications via osascript.
2. Safe shell escaping: avoids AppleScript injection.
3. Clean fallback: on non-Darwin platforms or headless environments, logs notification without error.
4. Non-blocking: 5.0 second timeout prevents command hangs.
"""

from __future__ import annotations

from decimal import Decimal
import logging
import platform
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def send_notification(
    title: str,
    message: str,
    subtitle: Optional[str] = None,
    sound: Optional[str] = "default",
    dry_run: bool = False,
) -> bool:
    """Send a native macOS user notification via osascript."""
    if platform.system() != "Darwin":
        logger.info(f"[BİLDİRİM - non-Darwin]: {title} | {subtitle or ''} | {message}")
        return True

    # Escape quotes and backslashes for AppleScript
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_msg = message.replace("\\", "\\\\").replace('"', '\\"')

    script_parts = [f'display notification "{safe_msg}" with title "{safe_title}"']
    if subtitle:
        safe_sub = subtitle.replace("\\", "\\\\").replace('"', '\\"')
        script_parts.append(f'subtitle "{safe_sub}"')
    if sound:
        script_parts.append(f'sound name "{sound}"')

    script = " ".join(script_parts)

    if dry_run:
        logger.debug(f"[Dry-run osascript]: {script}")
        return True

    try:
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=5.0,
        )
        return res.returncode == 0
    except Exception as exc:
        logger.warning(f"Bildirim gönderilemedi: {exc}")
        return False


def notify_forecast_generated(count: int, model_id: str, dry_run: bool = False) -> bool:
    """Send notification when morning 09:30 CET forecasts are generated and sealed."""
    return send_notification(
        title="◈ ETF Yatırım Masası",
        subtitle=f"Sabah Tahmini Tamamlandı ({count} Varlık)",
        message=f"{count} adet tahmin {model_id} ile üretildi ve mühürlendi.",
        sound="Glass",
        dry_run=dry_run,
    )


def notify_forecast_settled(
    count: int,
    hit_rate_pct: Decimal,
    mape_pct: Decimal,
    dry_run: bool = False,
) -> bool:
    """Send notification when evening 17:40 CET forecasts are settled."""
    return send_notification(
        title="◈ ETF Yatırım Masası",
        subtitle="Akşam Uzlaşma Raporu",
        message=f"{count} tahmin uzlaştırıldı. Günlük İsabet: %{hit_rate_pct:.1f} | MAPE: %{mape_pct:.2f}",
        sound="Hero",
        dry_run=dry_run,
    )


def notify_system_alert(level: str, message: str, dry_run: bool = False) -> bool:
    """Send high-priority system alert (e.g. session expiration or integrity failure)."""
    return send_notification(
        title=f"⚠️ ETF Masası {level.upper()}",
        subtitle="Sistem Müdahale Uyarısı",
        message=message,
        sound="Basso",
        dry_run=dry_run,
    )
