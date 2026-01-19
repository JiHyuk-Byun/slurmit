"""Rsync-based file transfer for slurmit.

Provides efficient file synchronization between local and remote hosts.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


# Default patterns to exclude from rsync
DEFAULT_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".venv",
    "venv",
    ".env",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "*.egg-info",
    ".tox",
    "dist",
    "build",
    ".DS_Store",
    "*.swp",
    "*.swo",
    "wandb",
    "outputs",
    "logs",
    "*.log",
]


@dataclass
class RsyncResult:
    """Result of an rsync operation."""

    success: bool
    stdout: str
    stderr: str
    return_code: int


def rsync_to_server(
    local_path: Path,
    remote_host: str,
    remote_path: str,
    user: str | None = None,
    exclude: list[str] | None = None,
    delete: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
    ssh_key: str | None = None,
    port: int = 22,
) -> RsyncResult:
    """Sync local directory to remote server using rsync.

    Args:
        local_path: Local directory to sync
        remote_host: Remote host address
        remote_path: Remote directory path
        user: SSH username (if not specified, uses current user)
        exclude: Patterns to exclude (extends default excludes)
        delete: Delete extraneous files from destination
        dry_run: Show what would be done without making changes
        verbose: Enable verbose output
        ssh_key: Path to SSH private key
        port: SSH port

    Returns:
        RsyncResult with success status and output
    """
    # Build exclude list
    excludes = list(DEFAULT_EXCLUDES)
    if exclude:
        excludes.extend(exclude)

    # Build rsync command
    cmd = ["rsync", "-az"]

    if verbose:
        cmd.append("-v")
        cmd.append("--progress")

    if delete:
        cmd.append("--delete")

    if dry_run:
        cmd.append("--dry-run")

    # Add excludes
    for pattern in excludes:
        cmd.append(f"--exclude={pattern}")

    # Build SSH command with options
    ssh_cmd = f"ssh -p {port}"
    if ssh_key:
        ssh_cmd += f" -i {ssh_key}"
    cmd.extend(["-e", ssh_cmd])

    # Source path (ensure trailing slash for directory sync)
    source = str(local_path)
    if not source.endswith("/"):
        source += "/"

    # Destination
    if user:
        dest = f"{user}@{remote_host}:{remote_path}/"
    else:
        dest = f"{remote_host}:{remote_path}/"

    cmd.extend([source, dest])

    # Run rsync
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        return RsyncResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )
    except FileNotFoundError:
        return RsyncResult(
            success=False,
            stdout="",
            stderr="rsync command not found. Please install rsync.",
            return_code=-1,
        )
    except Exception as e:
        return RsyncResult(
            success=False,
            stdout="",
            stderr=str(e),
            return_code=-1,
        )


def rsync_from_server(
    remote_host: str,
    remote_path: str,
    local_path: Path,
    user: str | None = None,
    exclude: list[str] | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    ssh_key: str | None = None,
    port: int = 22,
) -> RsyncResult:
    """Sync remote directory to local using rsync.

    Args:
        remote_host: Remote host address
        remote_path: Remote directory path
        local_path: Local directory to sync to
        user: SSH username
        exclude: Patterns to exclude
        dry_run: Show what would be done without making changes
        verbose: Enable verbose output
        ssh_key: Path to SSH private key
        port: SSH port

    Returns:
        RsyncResult with success status and output
    """
    # Build exclude list
    excludes = list(DEFAULT_EXCLUDES)
    if exclude:
        excludes.extend(exclude)

    # Build rsync command
    cmd = ["rsync", "-az"]

    if verbose:
        cmd.append("-v")
        cmd.append("--progress")

    if dry_run:
        cmd.append("--dry-run")

    # Add excludes
    for pattern in excludes:
        cmd.append(f"--exclude={pattern}")

    # Build SSH command with options
    ssh_cmd = f"ssh -p {port}"
    if ssh_key:
        ssh_cmd += f" -i {ssh_key}"
    cmd.extend(["-e", ssh_cmd])

    # Source
    if user:
        source = f"{user}@{remote_host}:{remote_path}/"
    else:
        source = f"{remote_host}:{remote_path}/"

    # Destination (ensure trailing slash)
    dest = str(local_path)
    if not dest.endswith("/"):
        dest += "/"

    cmd.extend([source, dest])

    # Run rsync
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        return RsyncResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )
    except FileNotFoundError:
        return RsyncResult(
            success=False,
            stdout="",
            stderr="rsync command not found. Please install rsync.",
            return_code=-1,
        )
    except Exception as e:
        return RsyncResult(
            success=False,
            stdout="",
            stderr=str(e),
            return_code=-1,
        )


def rsync_file_to_server(
    local_file: Path,
    remote_host: str,
    remote_path: str,
    user: str | None = None,
    ssh_key: str | None = None,
    port: int = 22,
) -> RsyncResult:
    """Sync a single file to remote server.

    Args:
        local_file: Local file to sync
        remote_host: Remote host address
        remote_path: Remote file path
        user: SSH username
        ssh_key: Path to SSH private key
        port: SSH port

    Returns:
        RsyncResult with success status and output
    """
    cmd = ["rsync", "-az"]

    # Build SSH command with options
    ssh_cmd = f"ssh -p {port}"
    if ssh_key:
        ssh_cmd += f" -i {ssh_key}"
    cmd.extend(["-e", ssh_cmd])

    # Source
    source = str(local_file)

    # Destination
    if user:
        dest = f"{user}@{remote_host}:{remote_path}"
    else:
        dest = f"{remote_host}:{remote_path}"

    cmd.extend([source, dest])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        return RsyncResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
        )
    except FileNotFoundError:
        return RsyncResult(
            success=False,
            stdout="",
            stderr="rsync command not found. Please install rsync.",
            return_code=-1,
        )
    except Exception as e:
        return RsyncResult(
            success=False,
            stdout="",
            stderr=str(e),
            return_code=-1,
        )


def check_rsync_available() -> bool:
    """Check if rsync is available on the system.

    Returns:
        True if rsync is available, False otherwise
    """
    try:
        result = subprocess.run(
            ["rsync", "--version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
