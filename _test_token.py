import urllib.request
import json
import os

token = os.environ.get("GH_TOKEN", "")
if not token:
    print("GH_TOKEN not set")
    raise SystemExit(1)

req = urllib.request.Request(
    "https://api.github.com/user",
    headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "DouBi-Push",
        "Accept": "application/vnd.github+json",
    },
)
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    print(f"OK: login={data.get('login')} name={data.get('name')} id={data.get('id')}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()[:300]}")
