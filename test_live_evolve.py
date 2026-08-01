import os
from pathlib import Path

env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from server.main import app
from starlette.testclient import TestClient

with TestClient(app) as client:
    res = client.post("/evolve", json={"text": "Add a dark mode toggle to the schedule topbar"})
    print("Status code:", res.status_code)
    print("Response JSON:", res.json())
    if res.status_code == 200:
        req_id = res.json()["id"]
        prop_res = client.get(f"/proposals/{req_id}")
        print("\nStored Proposal Detail:")
        import json
        print(json.dumps(prop_res.json(), indent=2)[:2000])
