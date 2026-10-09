"""Validate a single safe path component for agent workspace namespaces."""

import re


SAFE_WORKSPACE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z", re.ASCII)


def validate_workspace_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not SAFE_WORKSPACE_RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid goal research workspace run ID")
    return run_id
