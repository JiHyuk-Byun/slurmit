"""Git synchronization for myjob."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from myjob.core.models import GitConfig
from myjob.transport.ssh import SSHClient


@dataclass
class LocalGitInfo:
    """Information about local git repository."""

    repo_root: Path
    remote_url: str | None
    branch: str
    commit: str
    has_uncommitted: bool
    uncommitted_files: list[str]


def get_local_git_info() -> LocalGitInfo | None:
    """Get information about the local git repository.

    Returns None if not in a git repository.
    """
    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    # Get repo root
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    repo_root = Path(result.stdout.strip())

    # Get remote URL (origin)
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        remote_url = result.stdout.strip()
    except subprocess.CalledProcessError:
        remote_url = None

    # Get current branch
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    branch = result.stdout.strip()

    # Get current commit
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit = result.stdout.strip()

    # Check for uncommitted changes
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    uncommitted_files = [
        line[3:] for line in result.stdout.strip().split("\n") if line.strip()
    ]
    has_uncommitted = len(uncommitted_files) > 0

    return LocalGitInfo(
        repo_root=repo_root,
        remote_url=remote_url,
        branch=branch,
        commit=commit,
        has_uncommitted=has_uncommitted,
        uncommitted_files=uncommitted_files,
    )


def resolve_git_config(config: GitConfig, local_info: LocalGitInfo | None) -> GitConfig:
    """Resolve git configuration, using local info if auto_detect is enabled."""
    if not config.auto_detect or local_info is None:
        return config

    # Auto-detect values from local repo
    return GitConfig(
        repo_url=config.repo_url or local_info.remote_url,
        branch=local_info.branch if config.branch == "main" else config.branch,
        commit=config.commit or local_info.commit,
        auto_detect=config.auto_detect,
    )


class GitSync:
    """Git synchronization handler."""

    def __init__(self, ssh_client: SSHClient, config: GitConfig):
        """Initialize GitSync with SSH client and config."""
        self.ssh = ssh_client
        self.config = config

    def clone_or_update(self, target_dir: str) -> str:
        """Clone repository or update if it exists.

        Returns the final working directory path.
        """
        if not self.config.repo_url:
            raise ValueError("No repository URL configured")

        # Check if directory exists
        if self.ssh.directory_exists(target_dir):
            # Directory exists, try to update
            self._update_repo(target_dir)
        else:
            # Clone fresh
            self._clone_repo(target_dir)

        # Checkout specific commit if specified
        if self.config.commit:
            self._checkout_commit(target_dir, self.config.commit)

        return target_dir

    def _clone_repo(self, target_dir: str) -> None:
        """Clone the repository to target directory."""
        parent_dir = str(Path(target_dir).parent)
        repo_name = Path(target_dir).name

        self.ssh.ensure_directory(parent_dir)

        clone_cmd = f"git clone -b {self.config.branch} {self.config.repo_url} {target_dir}"
        result = self.ssh.run(clone_cmd, warn=True)

        if not result.ok:
            raise RuntimeError(f"Failed to clone repository: {result.stderr}")

    def _update_repo(self, target_dir: str) -> None:
        """Update existing repository."""
        # Fetch latest
        fetch_cmd = f"cd {target_dir} && git fetch origin"
        self.ssh.run(fetch_cmd, warn=True)

        # Checkout branch and pull
        checkout_cmd = f"cd {target_dir} && git checkout {self.config.branch}"
        self.ssh.run(checkout_cmd, warn=True)

        pull_cmd = f"cd {target_dir} && git pull origin {self.config.branch}"
        result = self.ssh.run(pull_cmd, warn=True)

        if not result.ok:
            # If pull fails, try reset
            reset_cmd = f"cd {target_dir} && git reset --hard origin/{self.config.branch}"
            self.ssh.run(reset_cmd, warn=True)

    def _checkout_commit(self, target_dir: str, commit: str) -> None:
        """Checkout a specific commit."""
        checkout_cmd = f"cd {target_dir} && git checkout {commit}"
        result = self.ssh.run(checkout_cmd, warn=True)

        if not result.ok:
            raise RuntimeError(f"Failed to checkout commit {commit}: {result.stderr}")

    def get_remote_commit(self, target_dir: str) -> str:
        """Get the current commit hash on remote."""
        result = self.ssh.run(f"cd {target_dir} && git rev-parse HEAD", warn=True)
        if not result.ok:
            raise RuntimeError("Failed to get commit hash")
        return result.stdout.strip()
