#!/usr/bin/env python3
"""Pre-create the Mem0 config directory and config.json.

This prevents the Mem0 SDK from needing to write at runtime,
which fails under systemd's ProtectHome=read-only.

Usage:
    sudo -u nella /home/nella/.local/bin/uv run python scripts/init_mem0_dir.py
"""

import json
import os
import uuid

mem0_dir = os.environ.get("MEM0_DIR", os.path.join(os.path.expanduser("~"), ".mem0"))
os.makedirs(mem0_dir, exist_ok=True)
print(f"Directory: {mem0_dir}")

config_path = os.path.join(mem0_dir, "config.json")
if os.path.exists(config_path):
    print(f"Config already exists: {config_path}")
else:
    config = {"user_id": str(uuid.uuid4())}
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
    print(f"Created: {config_path}")
