import json

from .store import default_data_dir


def _path():
    return default_data_dir() / "settings.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}


def save(**changes):
    data = load()
    data.update(changes)
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(data, indent=2))
