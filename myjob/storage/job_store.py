"""Local storage for job records."""

import json
from datetime import datetime
from pathlib import Path

from myjob.core.models import JobRecord


def get_jobs_dir() -> Path:
    """Get the directory for storing job records."""
    jobs_dir = Path.home() / ".myjob" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    return jobs_dir


def get_job_file(local_id: str) -> Path:
    """Get the path to a job record file."""
    return get_jobs_dir() / f"{local_id}.json"


def save_job(record: JobRecord) -> Path:
    """Save a job record to disk.

    Returns the path to the saved file.
    """
    job_file = get_job_file(record.local_id)
    with open(job_file, "w") as f:
        json.dump(record.model_dump(), f, indent=2)
    return job_file


def get_job(local_id: str) -> JobRecord | None:
    """Load a job record by local ID.

    Returns None if the job doesn't exist.
    """
    job_file = get_job_file(local_id)
    if not job_file.exists():
        return None

    with open(job_file) as f:
        data = json.load(f)
    return JobRecord(**data)


def update_job_status(local_id: str, status: str, slurm_job_id: str | None = None) -> bool:
    """Update the status of a job record.

    Returns True if successful, False if job doesn't exist.
    """
    record = get_job(local_id)
    if record is None:
        return False

    record.status = status
    if slurm_job_id:
        record.slurm_job_id = slurm_job_id

    save_job(record)
    return True


def list_jobs(limit: int = 20) -> list[JobRecord]:
    """List recent job records, sorted by submission time (newest first).

    Args:
        limit: Maximum number of records to return.

    Returns:
        List of JobRecord objects.
    """
    jobs_dir = get_jobs_dir()
    job_files = sorted(jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    records = []
    for job_file in job_files[:limit]:
        try:
            with open(job_file) as f:
                data = json.load(f)
            records.append(JobRecord(**data))
        except (json.JSONDecodeError, ValueError):
            # Skip invalid files
            continue

    return records


def find_job_by_prefix(prefix: str) -> JobRecord | None:
    """Find a job by ID prefix.

    Useful for allowing users to type partial IDs.
    """
    if len(prefix) < 3:
        raise ValueError("Job ID prefix must be at least 3 characters")

    jobs_dir = get_jobs_dir()
    matches = list(jobs_dir.glob(f"{prefix}*.json"))

    if len(matches) == 0:
        return None
    if len(matches) > 1:
        raise ValueError(f"Ambiguous job ID prefix: {prefix} matches {len(matches)} jobs")

    with open(matches[0]) as f:
        data = json.load(f)
    return JobRecord(**data)


def find_job_by_slurm_id(slurm_job_id: str) -> JobRecord | None:
    """Find a job by SLURM job ID."""
    for record in list_jobs(limit=100):
        if record.slurm_job_id == slurm_job_id:
            return record
    return None


def delete_job(local_id: str) -> bool:
    """Delete a job record.

    Returns True if deleted, False if not found.
    """
    job_file = get_job_file(local_id)
    if job_file.exists():
        job_file.unlink()
        return True
    return False


def create_job_record(
    local_id: str,
    name: str,
    host: str,
    remote_dir: str,
    log_dir: str,
    command: str,
    config_file: str | None = None,
    slurm_job_id: str | None = None,
    git_commit: str | None = None,
    git_branch: str | None = None,
) -> JobRecord:
    """Create and save a new job record."""
    record = JobRecord(
        local_id=local_id,
        slurm_job_id=slurm_job_id,
        name=name,
        config_file=config_file,
        host=host,
        remote_dir=remote_dir,
        log_dir=log_dir,
        status="SUBMITTED",
        submitted_at=datetime.now().isoformat(),
        git_commit=git_commit,
        git_branch=git_branch,
        command=command,
    )
    save_job(record)
    return record
