"""Metadata generation for myjob experiments.

Captures git state, config hash, and submission info for reproducibility.
"""

import hashlib
import json
import os
import socket
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class GitMetadata:
    """Git repository state information."""

    repo: str | None
    branch: str
    commit: str
    dirty: bool
    diff_file: str | None  # Path to uncommitted.patch if dirty


@dataclass
class JobMetadata:
    """Complete metadata for a submitted job."""

    job_name: str
    submitted_at: str
    submitted_from: str
    git: GitMetadata
    config_hash: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        return data

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "JobMetadata":
        """Create JobMetadata from dictionary."""
        git_data = data.get("git", {})
        git = GitMetadata(
            repo=git_data.get("repo"),
            branch=git_data.get("branch", ""),
            commit=git_data.get("commit", ""),
            dirty=git_data.get("dirty", False),
            diff_file=git_data.get("diff_file"),
        )
        return cls(
            job_name=data.get("job_name", ""),
            submitted_at=data.get("submitted_at", ""),
            submitted_from=data.get("submitted_from", ""),
            git=git,
            config_hash=data.get("config_hash", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "JobMetadata":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


def get_git_info() -> GitMetadata | None:
    """Get current git repository information.

    Returns None if not in a git repository.
    """
    try:
        # Check if we're in a git repo
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    # Get remote URL (origin)
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        repo = result.stdout.strip()
    except subprocess.CalledProcessError:
        repo = None

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
    dirty = bool(result.stdout.strip())

    return GitMetadata(
        repo=repo,
        branch=branch,
        commit=commit,
        dirty=dirty,
        diff_file=None,  # Will be set by save_uncommitted_patch if needed
    )


def save_uncommitted_patch(output_path: Path) -> str | None:
    """Save uncommitted changes as a patch file.

    Args:
        output_path: Directory to save the patch file

    Returns:
        Filename of the patch if there are changes, None otherwise
    """
    try:
        # Get diff of staged and unstaged changes
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        diff_content = result.stdout

        if not diff_content.strip():
            # Also check for untracked files
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            )
            if not result.stdout.strip():
                return None

        # Save the patch
        patch_file = output_path / "uncommitted.patch"
        patch_file.write_text(diff_content)
        return "uncommitted.patch"

    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def compute_config_hash(config_path: Path) -> str:
    """Compute SHA256 hash of the config file.

    Args:
        config_path: Path to the configuration file

    Returns:
        Hash string prefixed with 'sha256:'
    """
    if not config_path.exists():
        return "sha256:none"

    content = config_path.read_bytes()
    hash_value = hashlib.sha256(content).hexdigest()[:16]
    return f"sha256:{hash_value}"


def create_metadata(
    job_name: str,
    config_path: Path,
    output_dir: Path | None = None,
) -> JobMetadata:
    """Create metadata for a job submission.

    Captures git state, config hash, and submission info.

    Args:
        job_name: Name of the job
        config_path: Path to the configuration file
        output_dir: Optional directory to save uncommitted.patch

    Returns:
        JobMetadata with all captured information
    """
    # Get submission info
    hostname = socket.gethostname()
    username = os.environ.get("USER", "unknown")
    submitted_from = f"{username}@{hostname}"
    submitted_at = datetime.now().isoformat()

    # Get git info
    git_info = get_git_info()
    if git_info is None:
        git_info = GitMetadata(
            repo=None,
            branch="",
            commit="",
            dirty=False,
            diff_file=None,
        )

    # Save uncommitted changes if dirty and output_dir provided
    if git_info.dirty and output_dir:
        diff_file = save_uncommitted_patch(output_dir)
        git_info = GitMetadata(
            repo=git_info.repo,
            branch=git_info.branch,
            commit=git_info.commit,
            dirty=git_info.dirty,
            diff_file=diff_file,
        )

    # Compute config hash
    config_hash = compute_config_hash(config_path)

    return JobMetadata(
        job_name=job_name,
        submitted_at=submitted_at,
        submitted_from=submitted_from,
        git=git_info,
        config_hash=config_hash,
    )


def save_metadata(metadata: JobMetadata, output_path: Path) -> Path:
    """Save metadata to a JSON file.

    Args:
        metadata: The metadata to save
        output_path: Directory to save metadata.json

    Returns:
        Path to the saved metadata file
    """
    metadata_file = output_path / "metadata.json"
    metadata_file.write_text(metadata.to_json())
    return metadata_file


def load_metadata(metadata_path: Path) -> JobMetadata | None:
    """Load metadata from a JSON file.

    Args:
        metadata_path: Path to metadata.json

    Returns:
        JobMetadata if file exists and is valid, None otherwise
    """
    if not metadata_path.exists():
        return None

    try:
        content = metadata_path.read_text()
        return JobMetadata.from_json(content)
    except (json.JSONDecodeError, KeyError):
        return None
