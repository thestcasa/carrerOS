from __future__ import annotations

import json
import os
import time
from typing import NoReturn

from redis import Redis


def run_process(role: str) -> NoReturn:
    """Run a minimal durable process boundary until workflow handlers are registered."""
    redis_url = os.environ["REDIS_URL"]
    client = Redis.from_url(redis_url, decode_responses=True)
    channel = f"careeros:{role}:heartbeat"
    while True:
        client.set(channel, json.dumps({"role": role, "status": "ready"}), ex=90)
        time.sleep(30)
