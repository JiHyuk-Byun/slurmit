"""Local storage for job records.

Jobs are stored by name as the primary identifier.
"""

import json
from datetime import datetime
from pathlib import Path

from myjob.core.models import JobRecord


def get_jobs_dir() -> Path:
    """Get the directory for storing job records."""
    jobs_dir = Path.home() / ".myjob" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    return jobs_dir


def get_job_file(name: str) -> Path:
    """Get the path to a job record file by name."""
    # Sanitize name for filesystem
    safe_name = name.replace("/", "_").replace("\\", "_")
    return get_jobs_dir() / f"{safe_name}.json"


def save_job(record: JobRecord) -> Path:
    """Save a job record to disk.

    Returns the path to the saved file.
    """
    job_file = get_job_file(record.name)
    with open(job_file, "w") as f:
        json.dump(record.model_dump(), f, indent=2)
    return job_file


def get_job(name: str) -> JobRecord | None:
    """Load a job record by name.

    Returns None if the job doesn't exist.
    """
    job_file = get_job_file(name)
    if not job_file.exists():
        return None

    with open(job_file) as f:
        data = json.load(f)
    return JobRecord(**data)


def update_job_status(
    name: str,
    status: str,
    slurm_job_id: str | None = None,
    run_id: str | None = None,
    run_dir: str | None = None,
    log_dir: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> bool:
    """Update the status of a job record.

    Returns True if successful, False if job doesn't exist.
    """
    record = get_job(name)
    if record is None:
        return False

    record.status = status
    if slurm_job_id:
        record.slurm_job_id = slurm_job_id
    if run_id:
        record.run_id = run_id
    if run_dir:
        record.run_dir = run_dir
    if log_dir:
        record.log_dir = log_dir
    if started_at:
        record.started_at = started_at
    if completed_at:
        record.completed_at = completed_at

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


def find_job_by_name(name: str) -> JobRecord | None:
    """Find a job by exact name.

    This is the primary lookup method.
    """
    return get_job(name)


def find_job_by_prefix(prefix: str) -> JobRecord | None:
    """Find a job by name prefix.

    Useful for allowing users to type partial names.
    """
    if len(prefix) < 2:
        raise ValueError("Job name prefix must be at least 2 characters")

    jobs_dir = get_jobs_dir()
    matches = list(jobs_dir.glob(f"{prefix}*.json"))

    if len(matches) == 0:
        return None
    if len(matches) > 1:
        raise ValueError(f"Ambiguous job name prefix: {prefix} matches {len(matches)} jobs")

    with open(matches[0]) as f:
        data = json.load(f)
    return JobRecord(**data)


def find_job_by_slurm_id(slurm_job_id: str) -> JobRecord | None:
    """Find a job by SLURM job ID."""
    for record in list_jobs(limit=100):
        if record.slurm_job_id == slurm_job_id:
            return record
    return None


def find_job_by_run_id(run_id: str) -> JobRecord | None:
    """Find a job by run ID (name_timestamp format)."""
    for record in list_jobs(limit=100):
        if record.run_id == run_id:
            return record
    return None


def delete_job(name: str) -> bool:
    """Delete a job record.

    Returns True if deleted, False if not found.
    """
    job_file = get_job_file(name)
    if job_file.exists():
        job_file.unlink()
        return True
    return False


def create_job_record(
    name: str,
    host: str,
    user: str,
    queue_dir: str,
    command: str,
    config_file: str | None = None,
    slurm_job_id: str | None = None,
    git_commit: str | None = None,
    git_branch: str | None = None,
    config_hash: str | None = None,
) -> JobRecord:
    """Create and save a new job record.

    Args:
        name: Job name (primary identifier)
        host: Remote host address
        user: SSH username
        queue_dir: Remote queue directory path
        command: Executed command
        config_file: Path to config file used
        slurm_job_id: SLURM job ID (if already submitted)
        git_commit: Git commit hash
        git_branch: Git branch name
        config_hash: Config file hash

    Returns:
        Created JobRecord
    """
    record = JobRecord(
        name=name,
        slurm_job_id=slurm_job_id,
        config_file=config_file,
        host=host,
        user=user,
        queue_dir=queue_dir,
        status="QUEUED",
        submitted_at=datetime.now().isoformat(),
        git_commit=git_commit,
        git_branch=git_branch,
        config_hash=config_hash,
        command=command,
    )
    save_job(record)
    return record


def update_job_for_run(
    name: str,
    run_id: str,
    run_dir: str,
    log_dir: str,
    slurm_job_id: str,
) -> bool:
    """Update job record when it transitions from queue to running.

    Args:
        name: Job name
        run_id: Run ID (name_timestamp)
        run_dir: Path to run directory
        log_dir: Path to log directory
        slurm_job_id: SLURM job ID

    Returns:
        True if successful, False if job not found
    """
    record = get_job(name)
    if record is None:
        return False

    record.run_id = run_id
    record.run_dir = run_dir
    record.log_dir = log_dir
    record.slurm_job_id = slurm_job_id
    record.status = "SUBMITTED"
    record.started_at = datetime.now().isoformat()

    save_job(record)
    return True
