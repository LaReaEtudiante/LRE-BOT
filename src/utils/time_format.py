# ==========================
# LRE-BOT/src/utils/time_format.py
# ==========================
def format_seconds(seconds: int) -> str:
    """Convertit un nombre de secondes en format lisible : 1j 2h 3m 4s"""
    seconds = int(seconds)
    years, seconds = divmod(seconds, 31536000)
    months, seconds = divmod(seconds, 2592000)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []
    if years: parts.append(f"{years}a")
    if months: parts.append(f"{months}m")
    if days: parts.append(f"{days}j")
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    if seconds or not parts: parts.append(f"{seconds}s")

    return " ".join(parts)
