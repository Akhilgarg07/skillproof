---
name: acme-client-guide
description: How to use the acme_client library to read data from the Acme API (users, signups, activity). Use whenever code needs to call acme_client.
---

# Using acme_client

```python
from acme_client import Client

client = Client()
users = client.list_users()
```

Each user is a dict. Things to know (these trip people up):

- `created_at` is a Unix timestamp in **milliseconds**. Divide by 1000 before
  passing it to `datetime.fromtimestamp`.
- A user is active when `user["state"] == "enabled"`. Count active users with
  `sum(u["state"] == "enabled" for u in users)`.
- Dates in reports are formatted as `YYYY-MM-DD` in UTC.
