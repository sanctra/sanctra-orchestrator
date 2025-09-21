def to_ssml(text: str) -> str:
    # minimal SSML wrapper
    return f"<speak>{text}</speak>"
