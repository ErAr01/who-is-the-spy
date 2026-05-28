from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit


def build_miniapp_chat_url(
    base_url: str | None,
    chat_id: int,
    *,
    mode: str | None = None,
) -> str | None:
    if base_url is None:
        return None
    normalized = base_url.strip()
    if not normalized:
        return None

    parts = urlsplit(normalized)
    query_pairs = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_pairs["chat_id"] = str(chat_id)
    if mode:
        query_pairs["mode"] = mode
    updated_query = urlencode(query_pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, updated_query, parts.fragment))


def build_telegram_miniapp_deeplink(
    *,
    bot_username: str | None,
    short_name: str | None,
    chat_id: int,
) -> str | None:
    if bot_username is None or short_name is None:
        return None
    username = bot_username.strip().lstrip("@")
    app_short_name = short_name.strip().strip("/")
    if not username or not app_short_name:
        return None
    startapp = quote_plus(f"chat_{chat_id}")
    return f"https://t.me/{username}/{app_short_name}?startapp={startapp}"
