"""SSH connection management using Fabric."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fabric import Connection
from invoke.exceptions import UnexpectedExit

from myjob.core.models import ConnectionConfig


@dataclass
class CommandResult:
    """Result of a remote command execution."""

    stdout: str
    stderr: str
    return_code: int
    ok: bool


class SSHClient:
    """SSH client for remote operations using Fabric."""

    def __init__(self, config: ConnectionConfig):
        """Initialize SSH client with connection config."""
        self.config = config
        self._connection: Connection | None = None

    def connect(self) -> Connection:
        """Establish SSH connection."""
        connect_kwargs: dict[str, Any] = {}

        if self.config.key_file:
            key_path = Path(self.config.key_file).expanduser()
            connect_kwargs["key_filename"] = str(key_path)

        self._connection = Connection(
            host=self.config.host,
            user=self.config.user,
            port=self.config.port,
            connect_kwargs=connect_kwargs,
        )
        return self._connection

    @property
    def connection(self) -> Connection:
        """Get or create connection."""
        if self._connection is None:
            self.connect()
        return self._connection  # type: ignore

    def run(self, command: str, warn: bool = False, hide: bool = True) -> CommandResult:
        """Execute a command on the remote host.

        Args:
            command: Command to execute
            warn: If True, don't raise exception on non-zero exit
            hide: If True, don't print output to console

        Returns:
            CommandResult with stdout, stderr, return_code, and ok status
        """
        try:
            result = self.connection.run(command, warn=warn, hide=hide)
            return CommandResult(
                stdout=result.stdout.strip() if result.stdout else "",
                stderr=result.stderr.strip() if result.stderr else "",
                return_code=result.return_code,
                ok=result.ok,
            )
        except UnexpectedExit as e:
            return CommandResult(
                stdout=e.result.stdout.strip() if e.result.stdout else "",
                stderr=e.result.stderr.strip() if e.result.stderr else "",
                return_code=e.result.return_code,
                ok=False,
            )

    def run_checked(self, command: str, hide: bool = True) -> str:
        """Execute a command and return stdout, raising on error."""
        result = self.run(command, warn=False, hide=hide)
        if not result.ok:
            raise RuntimeError(f"Command failed: {command}\nStderr: {result.stderr}")
        return result.stdout

    def check_slurm_version(self) -> str:
        """Check and return SLURM version on remote."""
        result = self.run("sinfo --version", warn=True)
        if not result.ok:
            raise RuntimeError("SLURM is not available on the remote system")
        return result.stdout

    def list_partitions(self) -> list[str]:
        """List available SLURM partitions."""
        result = self.run("sinfo -h -o '%P'", warn=True)
        if not result.ok:
            return []
        partitions = []
        for line in result.stdout.strip().split("\n"):
            partition = line.strip().rstrip("*")  # Remove default marker
            if partition:
                partitions.append(partition)
        return partitions

    def ensure_directory(self, path: str) -> None:
        """Ensure a directory exists on remote."""
        expanded_path = self._expand_path(path)
        self.run_checked(f"mkdir -p {expanded_path}")

    def file_exists(self, path: str) -> bool:
        """Check if a file exists on remote."""
        expanded_path = self._expand_path(path)
        result = self.run(f"test -f {expanded_path}", warn=True)
        return result.ok

    def directory_exists(self, path: str) -> bool:
        """Check if a directory exists on remote."""
        expanded_path = self._expand_path(path)
        result = self.run(f"test -d {expanded_path}", warn=True)
        return result.ok

    def read_file(self, path: str) -> str:
        """Read a file from remote."""
        expanded_path = self._expand_path(path)
        return self.run_checked(f"cat {expanded_path}")

    def write_file(self, path: str, content: str) -> None:
        """Write content to a file on remote."""
        expanded_path = self._expand_path(path)
        # Use heredoc to handle multi-line content
        escaped_content = content.replace("'", "'\"'\"'")
        self.run_checked(f"cat > {expanded_path} << 'MYJOB_EOF'\n{content}\nMYJOB_EOF")

    def _expand_path(self, path: str) -> str:
        """Expand ~ in path."""
        if path.startswith("~"):
            return path  # Let the shell expand it
        return path

    def get_home_dir(self) -> str:
        """Get the home directory on remote."""
        return self.run_checked("echo $HOME")

    def close(self) -> None:
        """Close the SSH connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "SSHClient":
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()
