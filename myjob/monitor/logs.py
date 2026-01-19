"""Log retrieval and streaming for jobs."""

import time
from dataclasses import dataclass
from typing import Iterator

from myjob.core.models import JobRecord
from myjob.transport.ssh import SSHClient


@dataclass
class LogContent:
    """Content of log files."""

    stdout: str
    stderr: str
    stdout_path: str
    stderr_path: str


class LogMonitor:
    """Monitor and retrieve job logs."""

    def __init__(self, ssh_client: SSHClient):
        """Initialize log monitor."""
        self.ssh = ssh_client

    def get_log_paths(self, job_record: JobRecord) -> tuple[str, str]:
        """Get the paths to stdout and stderr log files.

        Returns (stdout_path, stderr_path).
        """
        log_dir = job_record.log_dir
        slurm_job_id = job_record.slurm_job_id or "*"

        # Try to find the actual log files
        # Pattern: job_<job_id>.out and job_<job_id>.err
        stdout_pattern = f"{log_dir}/*{slurm_job_id}*.out"
        stderr_pattern = f"{log_dir}/*{slurm_job_id}*.err"

        # Find matching files
        stdout_result = self.ssh.run(f"ls -1 {stdout_pattern} 2>/dev/null | head -1", warn=True)
        stderr_result = self.ssh.run(f"ls -1 {stderr_pattern} 2>/dev/null | head -1", warn=True)

        stdout_path = stdout_result.stdout.strip() if stdout_result.ok else ""
        stderr_path = stderr_result.stdout.strip() if stderr_result.ok else ""

        return stdout_path, stderr_path

    def get_logs(
        self, job_record: JobRecord, lines: int | None = None
    ) -> LogContent:
        """Get the content of log files.

        Args:
            job_record: Job record containing log directory info.
            lines: Number of lines to retrieve (from end). None for all.

        Returns:
            LogContent with stdout and stderr content.
        """
        stdout_path, stderr_path = self.get_log_paths(job_record)

        stdout = ""
        stderr = ""

        if stdout_path:
            if lines:
                result = self.ssh.run(f"tail -n {lines} {stdout_path}", warn=True)
            else:
                result = self.ssh.run(f"cat {stdout_path}", warn=True)
            stdout = result.stdout if result.ok else ""

        if stderr_path:
            if lines:
                result = self.ssh.run(f"tail -n {lines} {stderr_path}", warn=True)
            else:
                result = self.ssh.run(f"cat {stderr_path}", warn=True)
            stderr = result.stdout if result.ok else ""

        return LogContent(
            stdout=stdout,
            stderr=stderr,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    def tail_logs(
        self,
        job_record: JobRecord,
        follow: bool = False,
        lines: int = 50,
        stream: str = "stdout",
    ) -> Iterator[str]:
        """Tail log files with optional follow mode.

        Args:
            job_record: Job record containing log directory info.
            follow: If True, continuously follow the log.
            lines: Number of initial lines to show.
            stream: Which stream to tail ("stdout" or "stderr").

        Yields:
            Lines of log output.
        """
        stdout_path, stderr_path = self.get_log_paths(job_record)
        log_path = stdout_path if stream == "stdout" else stderr_path

        if not log_path:
            yield f"[No {stream} log file found]"
            return

        if follow:
            # Follow mode - poll for new content
            yield from self._follow_log(log_path, lines)
        else:
            # One-time tail
            result = self.ssh.run(f"tail -n {lines} {log_path}", warn=True)
            if result.ok:
                yield result.stdout
            else:
                yield f"[Error reading log: {result.stderr}]"

    def _follow_log(self, log_path: str, initial_lines: int = 50) -> Iterator[str]:
        """Follow a log file, yielding new content.

        Note: This uses polling since we're over SSH.
        """
        # Get initial content
        result = self.ssh.run(f"tail -n {initial_lines} {log_path}", warn=True)
        if result.ok:
            yield result.stdout

        # Track file position
        last_size_result = self.ssh.run(f"stat -c %s {log_path} 2>/dev/null || stat -f %z {log_path}", warn=True)
        last_size = int(last_size_result.stdout.strip()) if last_size_result.ok else 0

        # Poll for new content
        while True:
            time.sleep(1)  # Poll interval

            # Check current size
            size_result = self.ssh.run(f"stat -c %s {log_path} 2>/dev/null || stat -f %z {log_path}", warn=True)
            if not size_result.ok:
                continue

            current_size = int(size_result.stdout.strip())

            if current_size > last_size:
                # Read new content
                bytes_to_read = current_size - last_size
                result = self.ssh.run(
                    f"tail -c {bytes_to_read} {log_path}",
                    warn=True,
                )
                if result.ok and result.stdout:
                    yield result.stdout
                last_size = current_size

    def wait_for_log(self, job_record: JobRecord, timeout: int = 60) -> bool:
        """Wait for log file to appear.

        Args:
            job_record: Job record.
            timeout: Maximum seconds to wait.

        Returns:
            True if log file appeared, False if timed out.
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            stdout_path, _ = self.get_log_paths(job_record)
            if stdout_path:
                return True
            time.sleep(2)

        return False
