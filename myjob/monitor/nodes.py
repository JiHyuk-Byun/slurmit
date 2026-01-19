"""Node and GPU monitoring for SLURM clusters."""

import re
from dataclasses import dataclass
from typing import Optional

from myjob.transport.ssh import SSHClient


@dataclass
class GPUInfo:
    """GPU information for a node."""

    gpu_type: str  # e.g., "a100", "v100", "rtx3090"
    total: int  # Total GPUs on node
    used: int  # GPUs currently in use
    free: int  # Available GPUs

    @property
    def usage_str(self) -> str:
        """Return usage as 'free/total (type)' string."""
        return f"{self.free}/{self.total} ({self.gpu_type})"


@dataclass
class NodeInfo:
    """Information about a cluster node."""

    name: str  # Node name
    state: str  # idle, mixed, allocated, down, etc.
    partition: str  # Partition name
    cpus_total: int  # Total CPUs
    cpus_used: int  # CPUs in use
    memory_total: str  # Total memory (e.g., "256G")
    gpu: Optional[GPUInfo]  # GPU info if available

    @property
    def cpus_free(self) -> int:
        """Calculate free CPUs."""
        return self.cpus_total - self.cpus_used

    @property
    def cpu_usage_str(self) -> str:
        """Return CPU usage as 'used/total' string."""
        return f"{self.cpus_used}/{self.cpus_total}"


class NodeMonitor:
    """Monitor cluster nodes and GPUs using SLURM commands."""

    def __init__(self, ssh_client: SSHClient):
        """Initialize node monitor with SSH client."""
        self.ssh = ssh_client

    def get_nodes(self, partition: str | None = None) -> list[NodeInfo]:
        """Get information about cluster nodes.

        Args:
            partition: Filter by partition name (optional)

        Returns:
            List of NodeInfo objects
        """
        # Build sinfo command
        # Format: NodeName|Partition|State|CPUsState|Memory
        cmd = 'sinfo -N -h -o "%N|%P|%T|%C|%m"'
        if partition:
            cmd += f" -p {partition}"

        result = self.ssh.run(cmd, warn=True)
        if not result.ok or not result.stdout.strip():
            return []

        nodes = []
        seen_nodes = set()  # Track nodes to avoid duplicates from multiple partitions

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            parts = line.split("|")
            if len(parts) < 5:
                continue

            node_name = parts[0].strip()

            # Skip duplicates
            if node_name in seen_nodes:
                continue
            seen_nodes.add(node_name)

            partition_name = parts[1].strip().rstrip("*")  # Remove default marker
            state = parts[2].strip()

            # Parse CPU state (Allocated/Idle/Other/Total)
            cpu_state = parts[3].strip()
            cpus_used, cpus_total = self._parse_cpu_state(cpu_state)

            memory = parts[4].strip()
            # Convert memory to human-readable format
            memory_str = self._format_memory(memory)

            # Get GPU info for this node
            gpu_info = self._get_gpu_info(node_name)

            nodes.append(NodeInfo(
                name=node_name,
                state=state,
                partition=partition_name,
                cpus_total=cpus_total,
                cpus_used=cpus_used,
                memory_total=memory_str,
                gpu=gpu_info,
            ))

        return nodes

    def _parse_cpu_state(self, cpu_state: str) -> tuple[int, int]:
        """Parse CPU state string (A/I/O/T format).

        Args:
            cpu_state: String like "24/40/0/64" (Allocated/Idle/Other/Total)

        Returns:
            Tuple of (used, total)
        """
        try:
            parts = cpu_state.split("/")
            if len(parts) >= 4:
                allocated = int(parts[0])
                total = int(parts[3])
                return allocated, total
            elif len(parts) == 2:
                # Simple used/total format
                return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            pass
        return 0, 0

    def _format_memory(self, memory: str) -> str:
        """Format memory value to human-readable string."""
        try:
            # Memory is typically in MB from sinfo
            mem_mb = int(memory)
            if mem_mb >= 1024:
                return f"{mem_mb // 1024}G"
            return f"{mem_mb}M"
        except ValueError:
            return memory

    def _get_gpu_info(self, node_name: str) -> Optional[GPUInfo]:
        """Get GPU information for a specific node.

        Uses scontrol to query GRES (Generic RESource) information.
        """
        cmd = f"scontrol show node {node_name}"
        result = self.ssh.run(cmd, warn=True)

        if not result.ok or not result.stdout:
            return None

        output = result.stdout

        # Parse Gres and GresUsed fields
        # Example: Gres=gpu:a100:4
        # Example: GresUsed=gpu:a100:2(IDX:0-1)
        gres_match = re.search(r"Gres=gpu:(\w+):(\d+)", output)
        gres_used_match = re.search(r"GresUsed=gpu:(\w+):(\d+)", output)

        if not gres_match:
            # Try alternative format: Gres=gpu:4
            gres_match = re.search(r"Gres=gpu:(\d+)", output)
            if gres_match:
                total = int(gres_match.group(1))
                gpu_type = "gpu"

                # Get used count
                gres_used_match = re.search(r"GresUsed=gpu:(\d+)", output)
                used = int(gres_used_match.group(1)) if gres_used_match else 0

                return GPUInfo(
                    gpu_type=gpu_type,
                    total=total,
                    used=used,
                    free=total - used,
                )
            return None

        gpu_type = gres_match.group(1)
        total = int(gres_match.group(2))

        used = 0
        if gres_used_match:
            used = int(gres_used_match.group(2))

        return GPUInfo(
            gpu_type=gpu_type,
            total=total,
            used=used,
            free=total - used,
        )

    def get_summary(self) -> dict:
        """Get a summary of cluster GPU resources.

        Returns:
            Dictionary with GPU type as key and counts as values
        """
        nodes = self.get_nodes()

        summary = {
            "total_nodes": len(nodes),
            "nodes_by_state": {},
            "gpus_by_type": {},
            "total_gpus": 0,
            "free_gpus": 0,
        }

        for node in nodes:
            # Count nodes by state
            state = node.state
            summary["nodes_by_state"][state] = summary["nodes_by_state"].get(state, 0) + 1

            # Count GPUs
            if node.gpu:
                gpu_type = node.gpu.gpu_type
                if gpu_type not in summary["gpus_by_type"]:
                    summary["gpus_by_type"][gpu_type] = {"total": 0, "free": 0}

                summary["gpus_by_type"][gpu_type]["total"] += node.gpu.total
                summary["gpus_by_type"][gpu_type]["free"] += node.gpu.free
                summary["total_gpus"] += node.gpu.total
                summary["free_gpus"] += node.gpu.free

        return summary

    def get_available_nodes(
        self,
        min_gpus: int = 0,
        gpu_type: str | None = None,
        partition: str | None = None,
    ) -> list[NodeInfo]:
        """Get nodes with available resources.

        Args:
            min_gpus: Minimum number of free GPUs required
            gpu_type: Specific GPU type required
            partition: Filter by partition

        Returns:
            List of nodes meeting the criteria
        """
        nodes = self.get_nodes(partition=partition)

        available = []
        for node in nodes:
            # Skip down/drain nodes
            if node.state in ("down", "drain", "draining"):
                continue

            # Check GPU requirements
            if min_gpus > 0:
                if not node.gpu or node.gpu.free < min_gpus:
                    continue
                if gpu_type and node.gpu.gpu_type.lower() != gpu_type.lower():
                    continue

            available.append(node)

        return available


class LocalNodeMonitor:
    """Node monitor for local execution (no SSH required)."""

    def get_nodes(self, partition: str | None = None) -> list[NodeInfo]:
        """Get nodes using local SLURM commands."""
        import subprocess

        cmd = ['sinfo', '-N', '-h', '-o', '%N|%P|%T|%C|%m']
        if partition:
            cmd.extend(['-p', partition])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return []
        except FileNotFoundError:
            return []

        nodes = []
        seen_nodes = set()

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            parts = line.split("|")
            if len(parts) < 5:
                continue

            node_name = parts[0].strip()
            if node_name in seen_nodes:
                continue
            seen_nodes.add(node_name)

            partition_name = parts[1].strip().rstrip("*")
            state = parts[2].strip()
            cpu_state = parts[3].strip()
            memory = parts[4].strip()

            # Parse CPU state
            cpus_used, cpus_total = 0, 0
            try:
                cpu_parts = cpu_state.split("/")
                if len(cpu_parts) >= 4:
                    cpus_used = int(cpu_parts[0])
                    cpus_total = int(cpu_parts[3])
            except (ValueError, IndexError):
                pass

            # Format memory
            try:
                mem_mb = int(memory)
                memory_str = f"{mem_mb // 1024}G" if mem_mb >= 1024 else f"{mem_mb}M"
            except ValueError:
                memory_str = memory

            # Get GPU info
            gpu_info = self._get_gpu_info_local(node_name)

            nodes.append(NodeInfo(
                name=node_name,
                state=state,
                partition=partition_name,
                cpus_total=cpus_total,
                cpus_used=cpus_used,
                memory_total=memory_str,
                gpu=gpu_info,
            ))

        return nodes

    def _get_gpu_info_local(self, node_name: str) -> Optional[GPUInfo]:
        """Get GPU info using local scontrol command."""
        import subprocess

        try:
            result = subprocess.run(
                ['scontrol', 'show', 'node', node_name],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return None
        except FileNotFoundError:
            return None

        output = result.stdout

        # Parse Gres field
        gres_match = re.search(r"Gres=gpu:(\w+):(\d+)", output)
        gres_used_match = re.search(r"GresUsed=gpu:(\w+):(\d+)", output)

        if not gres_match:
            gres_match = re.search(r"Gres=gpu:(\d+)", output)
            if gres_match:
                total = int(gres_match.group(1))
                gres_used_match = re.search(r"GresUsed=gpu:(\d+)", output)
                used = int(gres_used_match.group(1)) if gres_used_match else 0
                return GPUInfo(gpu_type="gpu", total=total, used=used, free=total - used)
            return None

        gpu_type = gres_match.group(1)
        total = int(gres_match.group(2))
        used = int(gres_used_match.group(2)) if gres_used_match else 0

        return GPUInfo(gpu_type=gpu_type, total=total, used=used, free=total - used)

    def get_summary(self) -> dict:
        """Get cluster summary."""
        nodes = self.get_nodes()

        summary = {
            "total_nodes": len(nodes),
            "nodes_by_state": {},
            "gpus_by_type": {},
            "total_gpus": 0,
            "free_gpus": 0,
        }

        for node in nodes:
            state = node.state
            summary["nodes_by_state"][state] = summary["nodes_by_state"].get(state, 0) + 1

            if node.gpu:
                gpu_type = node.gpu.gpu_type
                if gpu_type not in summary["gpus_by_type"]:
                    summary["gpus_by_type"][gpu_type] = {"total": 0, "free": 0}
                summary["gpus_by_type"][gpu_type]["total"] += node.gpu.total
                summary["gpus_by_type"][gpu_type]["free"] += node.gpu.free
                summary["total_gpus"] += node.gpu.total
                summary["free_gpus"] += node.gpu.free

        return summary
