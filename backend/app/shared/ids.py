import uuid


def make_id() -> str:
    return str(uuid.uuid4())


def make_short_id(full_id: str) -> str:
    return full_id.replace("-", "")[:4]
