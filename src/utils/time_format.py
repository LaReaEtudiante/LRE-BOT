# ==========================
# LRE-BOT/src/utils/time_format.py
# ==========================
def format_seconds(seconds: int) -> str:
    """Convertit un nombre de secondes en format lisible : 1a 2mo 3j 4h 5min 6s"""
    seconds = int(seconds)
    years, seconds = divmod(seconds, 31536000)
    months, seconds = divmod(seconds, 2592000)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []
    if years:
        parts.append(f"{years}a")
    if months:
        parts.append(f"{months}mo")
    if days:
        parts.append(f"{days}j")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}min")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)
# --- TESTS TEMPORAIRES ---
if __name__ == "__main__":
    examples = [
        45,          # 45s
        3600 + 62,   # 1h 1min 2s
        86400 * 3,   # 3j
        2592000 + 70,# 1mo 1min 10s
        31536000*2 + 86400*5 + 3661, # 2a 5j 1h 1min 1s
    ]
    for e in examples:
        print(f"{e} sec -> {format_seconds(e)}")
