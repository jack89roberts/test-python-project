"""
Load config dict used across the dummy generation scripts.
"""
from __future__ import annotations

import yaml

with open("dummy_model_config.yaml") as f:
    config = yaml.safe_load(f)
