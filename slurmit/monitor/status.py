"""Job status monitoring using SLURM commands."""

from dataclasses import dataclass
from enum import Enum

from slurmit.transport.ssh import SSHClient


class JobState(Enum):
    """SLURM job states."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    NODE_FAIL = "NODE_FAIL"
    PREEMPTED = "PREEMPTED"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, state: str) -> "JobState":
        """Convert SLURM state string to JobState enum."""
        state = state.upper().strip()
        try:
            return cls(state)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class JobStatus:
    """Status information for a SLURM job."""

    job_id: str
    name: str
    state: JobState
    partition: str
    node: str | None
    elapsed: str
    start_time: str | None
    end_time: str | None
    exit_code: str | None


class StatusMonitor:
    """Monitor job status using SLURM commands."""

    def __init__(self, ssh_client: SSHClient):
        """Initialize status monitor."""
        self.ssh = ssh_client

    def get_status(self, slurm_job_id: str) -> JobStatus | None:
        """Get the status of a job.

        First tries squeue for running/pending jobs,
        then falls back to sacct for completed jobs.
        """
        # Try squeue first for running jobs
        status = self._get_from_squeue(slurm_job_id)
        if status:
            return status

        # Fall back to sacct for completed jobs
        return self._get_from_sacct(slurm_job_id)

    def _get_from_squeue(self, slurm_job_id: str) -> JobStatus | None:
        """Get job status from squeue (running/pending jobs)."""
        cmd = (
            f"squeue -j {slurm_job_id} -h "
            f'-o "%i|%j|%T|%P|%N|%M|%S"'
        )
        result = self.ssh.run(cmd, warn=True)

        if not result.ok or not result.stdout.strip():
            return None

        parts = result.stdout.strip().split("|")
        if len(parts) < 7:
            return None

        return JobStatus(
            job_id=parts[0],
            name=parts[1],
            state=JobState.from_string(parts[2]),
            partition=parts[3],
            node=parts[4] if parts[4] else None,
            elapsed=parts[5],
            start_time=parts[6] if parts[6] != "N/A" else None,
            end_time=None,
            exit_code=None,
        )

    def _get_from_sacct(self, slurm_job_id: str) -> JobStatus | None:
        """Get job status from sacct (completed jobs)."""
        cmd = (
            f"sacct -j {slurm_job_id} -n -X "
            f'-o "JobID,JobName,State,Partition,NodeList,Elapsed,Start,End,ExitCode" '
            f"--parsable2"
        )
        result = self.ssh.run(cmd, warn=True)

        if not result.ok or not result.stdout.strip():
            return None

        # Take the first line (main job, not steps)
        lines = result.stdout.strip().split("\n")
        if not lines:
            return None

        parts = lines[0].split("|")
        if len(parts) < 9:
            return None

        return JobStatus(
            job_id=parts[0],
            name=parts[1],
            state=JobState.from_string(parts[2]),
            partition=parts[3],
            node=parts[4] if parts[4] else None,
            elapsed=parts[5],
            start_time=parts[6] if parts[6] != "Unknown" else None,
            end_time=parts[7] if parts[7] != "Unknown" else None,
            exit_code=parts[8],
        )

    def list_running_jobs(self, user: str | None = None) -> list[JobStatus]:
        """List all running/pending jobs for a user."""
        user_filter = f"-u {user}" if user else ""
        cmd = f'squeue {user_filter} -h -o "%i|%j|%T|%P|%N|%M|%S"'

        result = self.ssh.run(cmd, warn=True)
        if not result.ok or not result.stdout.strip():
            return []

        jobs = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            parts = line.split("|")
            if len(parts) < 7:
                continue

            jobs.append(
                JobStatus(
                    job_id=parts[0],
                    name=parts[1],
                    state=JobState.from_string(parts[2]),
                    partition=parts[3],
                    node=parts[4] if parts[4] else None,
                    elapsed=parts[5],
                    start_time=parts[6] if parts[6] != "N/A" else None,
                    end_time=None,
                    exit_code=None,
                )
            )

        return jobs

    def is_running(self, slurm_job_id: str) -> bool:
        """Check if a job is currently running or pending."""
        status = self._get_from_squeue(slurm_job_id)
        return status is not None

    def is_completed(self, slurm_job_id: str) -> bool:
        """Check if a job has completed (successfully or not)."""
        status = self.get_status(slurm_job_id)
        if status is None:
            return False
        return status.state in (
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.TIMEOUT,
            JobState.NODE_FAIL,
            JobState.OUT_OF_MEMORY,
        )
