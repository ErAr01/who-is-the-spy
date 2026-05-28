from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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
