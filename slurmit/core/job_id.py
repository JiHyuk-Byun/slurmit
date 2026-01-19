"""Local job ID generation for slurmit."""

import hashlib
import time
import uuid


def generate_job_id() -> str:
    """Generate a unique 6-character local job ID.

    Uses a combination of timestamp and random UUID to ensure uniqueness,
    then takes a 6-character hash prefix.
    """
    unique_str = f"{time.time()}-{uuid.uuid4()}"
    hash_digest = hashlib.sha256(unique_str.encode()).hexdigest()
    return hash_digest[:6]


def is_valid_job_id(job_id: str) -> bool:
    """Check if a string is a valid local job ID format."""
    if len(job_id) != 6:
        return False
    return all(c in "0123456789abcdef" for c in job_id.lower())
