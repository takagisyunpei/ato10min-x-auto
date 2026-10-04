def build_text(item):
    text = item["post_text"].strip()

    if item["slot"] == "note" and NOTE_URL:
        suffix = (
            "\n\n"
            "▼10分で読める解決策はこちら\n"
            + NOTE_URL
        )

        max_body_length = 280 - len(suffix)

        if len(text) > max_body_length:
            text = text[:max_body_length - 1].rstrip() + "…"

        text += suffix

    else:
        if len(text) > 280:
            text = text[:279].rstrip() + "…"

    return text
