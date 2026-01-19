# myjob

CLI tool for submitting and managing SLURM jobs on remote clusters.

## Architecture

```
LOCAL (User's PC)              SERVER (SLURM Cluster)
─────────────────              ─────────────────────
myjob submit ─── rsync ──────→ ~/myjob/queue/
                               myjob run ──→ sbatch
```

**Key Design:**
- `myjob submit` runs locally: transfers code via rsync
- `myjob run` runs on server: submits job to SLURM
- No git push required - direct file transfer
- Experiment versioning with git state capture

## Installation

```bash
# Install on both local machine and server
pip install -e .
```

## Quick Start

```bash
# 1. Create configuration
myjob init

# 2. Edit myjob.yaml with your settings

# 3. Submit from local (transfers code to server)
myjob submit -n my-experiment

# 4. SSH to server and run
ssh user@cluster
myjob run my-experiment

# 5. Check status (from local or server)
myjob status my-experiment
myjob logs my-experiment -f
```

## Commands

### Local Commands

```bash
myjob submit -n <name>        # Transfer code+config to server
myjob submit -n <name> --dry-run
myjob status <name>           # Check job status
myjob logs <name> -f          # View logs (follow mode)
myjob list                    # List submitted jobs
myjob cancel <name>           # Cancel a running job
```

### Server Commands

```bash
myjob run <name>              # Run a queued job
myjob run <name> -w           # Run and wait for completion
myjob run <name> -f           # Run and follow logs
myjob list --queue            # List queued jobs
myjob list --runs             # List run history
myjob nodes                   # Show cluster node/GPU status
myjob nodes -p gpu            # Filter by partition
myjob reproduce <run_id>      # Reproduce a past experiment
```

## Server Directory Structure

```
~/myjob/
├── queue/                        # Pending jobs (after submit)
│   └── my-exp/
│       ├── code/                 # Synced source code
│       ├── myjob.yaml            # Experiment config
│       └── metadata.json         # Version info (auto-generated)
│
├── runs/                         # Execution history
│   ├── my-exp_20240119_143022/   # With timestamp
│   │   ├── code/
│   │   ├── myjob.yaml
│   │   ├── metadata.json
│   │   └── logs/
│   └── my-exp_20240119_150512/
│
└── active/                       # Currently running (symlinks)
    └── my-exp -> ../runs/my-exp_20240119_150512/
```

## Configuration

### myjob.yaml

```yaml
name: my-experiment

connection:
  host: cluster.example.com
  user: myuser

slurm:
  partition: gpu
  account: my-account

resources:
  gpus: 1
  memory: 32G
  time: "4:00:00"

execution:
  command: python train.py
  modules:
    - cuda/11.8
    - anaconda3
  setup_commands:
    - conda activate myenv
```

### secret.yaml

Sensitive data stored separately:

```yaml
env_vars:
  WANDB_API_KEY: your-api-key
  HF_TOKEN: your-token
```

## Version Control

Each experiment automatically captures:
- Git commit hash
- Branch name
- Uncommitted changes (saved as patch)
- Config file hash

```bash
# View metadata
cat ~/myjob/runs/my-exp_20240119_143022/metadata.json

# Reproduce a past experiment
myjob reproduce my-exp_20240119_143022
```

### metadata.json Example

```json
{
  "job_name": "my-exp",
  "submitted_at": "2024-01-19T14:30:22",
  "submitted_from": "user@local-machine",
  "git": {
    "repo": "https://github.com/user/project",
    "branch": "main",
    "commit": "a1b2c3d4e5f6",
    "dirty": true,
    "diff_file": "uncommitted.patch"
  },
  "config_hash": "sha256:e4f5g6h7..."
}
```

## Node/GPU Monitoring

```bash
# Show cluster status
myjob nodes

# Example output:
CLUSTER STATUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NODE          STATE      PARTITION   CPU (used/total)   GPU (free/total)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
gpu-node-01   mixed      gpu         24/64              2/4 (a100)
gpu-node-02   allocated  gpu         64/64              0/4 (a100)
gpu-node-03   idle       gpu         0/64               4/4 (a100)

GPU Summary:
  Total GPUs: 12
  Free GPUs:  6
  A100: 6/12 available
```

## Workflow Example

```bash
# Local: develop and test code

# Local: submit experiment
myjob submit -n train-v1 --exclude "data/*"

# Server: check queue and run
ssh cluster
myjob list --queue
myjob run train-v1 -w

# Local: monitor progress
myjob status train-v1
myjob logs train-v1 -f

# Later: reproduce the experiment
myjob reproduce train-v1_20240119_143022
```

## License

MIT
