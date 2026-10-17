"""acme_client - a tiny offline stand-in for the Acme API client (v2.0)."""

_USERS = [
    {"id": 1, "name": "Mira", "active": True, "state": "enabled", "created_at": 1757894400},
    {"id": 2, "name": "Tom", "active": False, "state": "enabled", "created_at": 1758758400},
    {"id": 3, "name": "Priya", "active": True, "state": "enabled", "created_at": 1760227200},
    {"id": 4, "name": "Jonas", "active": False, "state": "enabled", "created_at": 1759363200},
    {"id": 5, "name": "Ana", "active": True, "state": "enabled", "created_at": 1758326400},
]


class Client:
    def list_users(self) -> list[dict]:
        """All users, as dicts."""
        return [dict(user) for user in _USERS]
