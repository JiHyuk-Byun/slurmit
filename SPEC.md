# myjob - SLURM Job Submission CLI

로컬에서 원격 SLURM 클러스터로 job을 제출하고 관리하는 CLI 도구

## 프로젝트 개요

### 목표
- 로컬에서 간단한 명령으로 SLURM job 제출
- Git 기반 코드 동기화 (커밋된 코드만)
- Job 상태 모니터링 및 로그 조회
- 클러스터 노드/GPU 상태 확인

### 기술 스택
- **언어**: Python 3.10+
- **CLI**: typer
- **SSH**: fabric
- **Config**: pydantic + pyyaml
- **코드 동기화**: git (clone)

---

## 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LOCAL (Client)                                  │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐   │
│  │ Phase 1 │───▶│ Phase 2 │───▶│ Phase 3 │───▶│ Phase 4 │───▶│ Phase 5 │   │
│  │  Parse  │    │   SSH   │    │   Git   │    │ Submit  │    │ Monitor │   │
│  │  Config │    │ Connect │    │  Clone  │    │   Job   │    │         │   │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ SSH (fabric)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            REMOTE (SLURM Cluster)                            │
│                                                                              │
│   ~/.myjob/workspaces/{job_id}/                                             │
│   ├── (git cloned repo)                                                     │
│   ├── job.sh                                                                │
│   ├── env.sh                                                                │
│   └── logs/                                                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 프로젝트 디렉토리 구조

```
myjob/
├── pyproject.toml
├── README.md
│
├── myjob/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py              # Entry point, typer app
│   │   └── commands/
│   │       ├── __init__.py
│   │       ├── submit.py        # myjob submit
│   │       ├── status.py        # myjob status
│   │       ├── logs.py          # myjob logs
│   │       ├── cancel.py        # myjob cancel
│   │       ├── list.py          # myjob list
│   │       └── nodes.py         # myjob nodes
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py            # Config loading & validation
│   │   ├── models.py            # Pydantic models
│   │   └── job_id.py            # Local job ID generation
│   │
│   ├── transport/
│   │   ├── __init__.py
│   │   ├── ssh.py               # SSH connection (fabric)
│   │   └── git_sync.py          # Git clone to remote
│   │
│   ├── backend/
│   │   ├── __init__.py
│   │   └── slurm.py             # SLURM script generation & submission
│   │
│   ├── monitor/
│   │   ├── __init__.py
│   │   ├── status.py            # Job status (squeue, sacct)
│   │   ├── logs.py              # Log viewing
│   │   └── nodes.py             # Node/GPU status
│   │
│   └── storage/
│       ├── __init__.py
│       └── job_store.py         # Local job history (JSON files)
│
└── tests/
    └── ...
```

---

## 사용자 파일 구조

```
user-project/
├── myjob.yaml        # 메인 설정 (git에 커밋 OK)
├── secret.yaml       # 민감 정보 (.gitignore에 추가)
├── .gitignore
└── src/
    └── ...
```

---

## Phase 1: 입력 처리 및 검증

### 설정 우선순위

```
CLI args > myjob.yaml > secret.yaml > defaults
```

### Config 스키마 (Pydantic)

```python
# myjob/core/models.py

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict
from pathlib import Path

class ConnectionConfig(BaseModel):
    host: str
    port: int = 22
    user: Optional[str] = None  # None이면 현재 사용자
    key_path: Optional[str] = None  # None이면 기본 SSH 키

class SlurmConfig(BaseModel):
    """SLURM 전용 옵션"""
    partition: Optional[str] = None
    account: Optional[str] = None
    qos: Optional[str] = None
    constraint: Optional[str] = None  # 노드 제약 (e.g., "a100")
    reservation: Optional[str] = None
    
    # 배열 작업
    array: Optional[str] = None  # "1-100", "1-100%10"
    
    # 의존성
    dependency: Optional[str] = None  # "afterok:12345"
    
    # 추가 sbatch 옵션 (escape hatch)
    extra_args: List[str] = []  # ["--exclusive", "--requeue"]

class ResourceConfig(BaseModel):
    cpus: int = Field(default=1, ge=1)
    memory: str = "4G"
    gpus: int = Field(default=0, ge=0)
    gpu_type: Optional[str] = None  # "a100", "v100"
    nodes: int = Field(default=1, ge=1)
    time: str = "1:00:00"  # 기본 1시간
    
    @validator('memory')
    def validate_memory(cls, v):
        """4G, 4096M, 4096 등 파싱"""
        import re
        match = re.match(r'^(\d+)([GMK]?)$', v.upper())
        if not match:
            raise ValueError(f"Invalid memory format: {v}")
        return v

class GitConfig(BaseModel):
    repo: Optional[str] = None  # None이면 자동 감지
    branch: Optional[str] = None  # None이면 현재 브랜치
    commit: Optional[str] = None  # None이면 HEAD

class ExecutionConfig(BaseModel):
    command: Optional[str] = None
    script: Optional[str] = None
    working_dir: str = "."
    env: Dict[str, str] = {}
    
    # 실행 전/후 훅
    setup: Optional[str] = None  # "module load cuda/11.8"
    teardown: Optional[str] = None

class OutputConfig(BaseModel):
    stdout: str = "logs/stdout_%j.log"
    stderr: str = "logs/stderr_%j.log"
    fetch: List[str] = []  # 완료 후 가져올 파일
    cleanup: bool = False  # 완료 후 원격 workspace 삭제

class JobConfig(BaseModel):
    """최종 통합 설정"""
    name: Optional[str] = None
    
    connection: ConnectionConfig
    slurm: SlurmConfig = SlurmConfig()
    resources: ResourceConfig = ResourceConfig()
    git: GitConfig = GitConfig()
    execution: ExecutionConfig
    output: OutputConfig = OutputConfig()
    
    tags: List[str] = []
```

### myjob.yaml 예시

```yaml
name: gpt-training

connection:
  host: cluster.example.com
  user: myuser

slurm:
  partition: gpu
  account: research-lab
  qos: normal

resources:
  gpus: 2
  gpu_type: a100
  cpus: 8
  memory: 32G
  time: "24:00:00"

execution:
  command: python train.py --epochs 100
  setup: |
    module load cuda/11.8
    module load anaconda3
    conda activate myenv

output:
  fetch:
    - outputs/
    - logs/
```

### secret.yaml 예시

```yaml
# .gitignore에 추가할 것
env:
  WANDB_API_KEY: "abc123..."
  HF_TOKEN: "hf_xxxxx..."

# SSH 키 (선택)
connection:
  key_path: ~/.ssh/my_private_key
```

### Config 로드 로직

```python
# myjob/core/config.py

class ConfigLoader:
    def load(self, config_file: Optional[str], cli_args: dict) -> JobConfig:
        """
        1. myjob.yaml 로드
        2. secret.yaml 병합 (같은 디렉토리)
        3. 글로벌 secret (~/.myjob/secret.yaml) 병합
        4. CLI args 오버라이드
        5. Pydantic 검증
        """
        merged = {}
        
        # 1. myjob.yaml
        config_path = config_file or self._find_config()
        if config_path:
            merged = self._load_yaml(config_path)
        
        # 2. secret.yaml (프로젝트)
        secret_path = Path(config_path).parent / "secret.yaml"
        if secret_path.exists():
            secrets = self._load_yaml(secret_path)
            merged = self._deep_merge(merged, secrets)
        
        # 3. secret.yaml (글로벌)
        global_secret = Path.home() / ".myjob" / "secret.yaml"
        if global_secret.exists():
            global_secrets = self._load_yaml(global_secret)
            merged = self._deep_merge(global_secrets, merged)
        
        # 4. CLI args
        merged = self._deep_merge(merged, cli_args)
        
        # 5. 검증
        return JobConfig(**merged)
```

---

## Phase 2: SSH 연결

### 구현

```python
# myjob/transport/ssh.py

from fabric import Connection
from dataclasses import dataclass

@dataclass
class RemoteInfo:
    slurm_version: str
    home_dir: str
    workspace_base: str
    available_partitions: list[str]

class SSHClient:
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.conn: Connection = None
        self.remote_info: RemoteInfo = None
    
    def connect(self) -> None:
        """SSH 연결 수립"""
        connect_kwargs = {}
        if self.config.key_path:
            connect_kwargs["key_filename"] = self.config.key_path
        
        self.conn = Connection(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            connect_kwargs=connect_kwargs,
            connect_timeout=30,
        )
        
        # 연결 테스트
        self.conn.run("echo 'connected'", hide=True)
    
    def check_environment(self) -> RemoteInfo:
        """원격 환경 확인"""
        # SLURM 버전
        result = self.conn.run("sinfo --version", hide=True, warn=True)
        if result.failed:
            raise EnvironmentError("SLURM not found on remote server")
        slurm_version = result.stdout.strip()
        
        # 홈 디렉토리
        home_dir = self.conn.run("echo $HOME", hide=True).stdout.strip()
        
        # 파티션 목록
        result = self.conn.run("sinfo -h -o '%P'", hide=True)
        partitions = [p.strip().rstrip('*') for p in result.stdout.splitlines()]
        
        self.remote_info = RemoteInfo(
            slurm_version=slurm_version,
            home_dir=home_dir,
            workspace_base=f"{home_dir}/.myjob/workspaces",
            available_partitions=partitions,
        )
        return self.remote_info
    
    def setup_workspace(self, job_id: str) -> str:
        """원격 workspace 생성"""
        workspace = f"{self.remote_info.workspace_base}/{job_id}"
        self.conn.run(f"mkdir -p {workspace}/logs", hide=True)
        return workspace
    
    def run(self, command: str, **kwargs):
        return self.conn.run(command, **kwargs)
    
    def close(self):
        if self.conn:
            self.conn.close()
```

### 에러 처리
- 연결 실패 시 재시도 3회
- 타임아웃 30초

---

## Phase 3: Git 동기화

### 정책
- **커밋된 코드만 사용** (uncommitted 변경사항 무시)
- uncommitted 변경사항이 있으면 경고 출력 (--force로 무시 가능)

### 구현

```python
# myjob/transport/git_sync.py

import subprocess
from dataclasses import dataclass

@dataclass
class GitInfo:
    repo_url: str
    branch: str
    commit_hash: str
    commit_message: str

class GitSyncer:
    def get_local_git_info(self) -> GitInfo:
        """로컬 git 정보 추출"""
        repo_url = self._run_git("remote", "get-url", "origin")
        branch = self._run_git("branch", "--show-current")
        commit_hash = self._run_git("rev-parse", "HEAD")
        commit_message = self._run_git("log", "-1", "--format=%s")
        
        return GitInfo(repo_url, branch, commit_hash, commit_message)
    
    def check_clean(self) -> bool:
        """uncommitted 변경사항 확인"""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True
        )
        return len(result.stdout.strip()) == 0
    
    def sync_to_remote(self, ssh_client: SSHClient, workspace: str, git_info: GitInfo):
        """원격에 git clone"""
        commands = f"""
        git clone --branch {git_info.branch} --depth 1 {git_info.repo_url} {workspace}
        cd {workspace}
        git checkout {git_info.commit_hash}
        """
        ssh_client.run(commands, hide=True)
    
    def _run_git(self, *args) -> str:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
```

---

## Phase 4: Job 제출

### sbatch 스크립트 생성

```python
# myjob/backend/slurm.py

class SlurmBackend:
    def generate_script(self, config: JobConfig, workspace: str) -> str:
        lines = ["#!/bin/bash"]
        
        # Job 이름
        if config.name:
            lines.append(f"#SBATCH --job-name={config.name}")
        
        # 리소스
        lines.append(f"#SBATCH --nodes={config.resources.nodes}")
        lines.append(f"#SBATCH --cpus-per-task={config.resources.cpus}")
        lines.append(f"#SBATCH --mem={config.resources.memory}")
        lines.append(f"#SBATCH --time={config.resources.time}")
        
        # GPU
        if config.resources.gpus > 0:
            gpu_spec = f"gpu:{config.resources.gpus}"
            if config.resources.gpu_type:
                gpu_spec = f"gpu:{config.resources.gpu_type}:{config.resources.gpus}"
            lines.append(f"#SBATCH --gres={gpu_spec}")
        
        # SLURM 옵션
        if config.slurm.partition:
            lines.append(f"#SBATCH --partition={config.slurm.partition}")
        if config.slurm.account:
            lines.append(f"#SBATCH --account={config.slurm.account}")
        if config.slurm.qos:
            lines.append(f"#SBATCH --qos={config.slurm.qos}")
        if config.slurm.constraint:
            lines.append(f"#SBATCH --constraint={config.slurm.constraint}")
        if config.slurm.array:
            lines.append(f"#SBATCH --array={config.slurm.array}")
        if config.slurm.dependency:
            lines.append(f"#SBATCH --dependency={config.slurm.dependency}")
        
        # 로그 경로
        lines.append(f"#SBATCH --output={workspace}/logs/stdout_%j.log")
        lines.append(f"#SBATCH --error={workspace}/logs/stderr_%j.log")
        
        # 추가 옵션
        for arg in config.slurm.extra_args:
            lines.append(f"#SBATCH {arg}")
        
        lines.append("")
        lines.append(f"cd {workspace}")
        lines.append("source ./env.sh")
        lines.append("")
        
        # Setup
        if config.execution.setup:
            lines.append("# Setup")
            lines.append(config.execution.setup)
            lines.append("")
        
        # 메인 명령
        lines.append("# Main command")
        if config.execution.script:
            lines.append(f"bash {config.execution.script}")
        else:
            lines.append(config.execution.command)
        
        # Teardown
        if config.execution.teardown:
            lines.append("")
            lines.append("# Teardown")
            lines.append(config.execution.teardown)
        
        return "\n".join(lines)
    
    def generate_env_script(self, env: dict) -> str:
        """env.sh 생성"""
        lines = ["#!/bin/bash"]
        for key, value in env.items():
            lines.append(f'export {key}="{value}"')
        return "\n".join(lines)
    
    def submit(self, ssh_client: SSHClient, workspace: str) -> str:
        """sbatch 실행 및 job ID 반환"""
        result = ssh_client.run(
            f"sbatch {workspace}/job.sh",
            hide=True
        )
        # "Submitted batch job 12345678" 파싱
        output = result.stdout.strip()
        slurm_job_id = output.split()[-1]
        return slurm_job_id
```

### 로컬 Job 저장

```python
# myjob/storage/job_store.py

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

@dataclass
class JobRecord:
    local_id: str           # 로컬 추적 ID (e.g., "a1b2c3")
    slurm_job_id: str       # SLURM job ID (e.g., "12345678")
    name: str
    host: str
    workspace: str
    git_repo: str
    git_branch: str
    git_commit: str
    status: str             # PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    submitted_at: str       # ISO format
    config: dict            # 원본 config

class JobStore:
    def __init__(self):
        self.store_path = Path.home() / ".myjob" / "jobs"
        self.store_path.mkdir(parents=True, exist_ok=True)
    
    def save(self, job: JobRecord):
        path = self.store_path / f"{job.local_id}.json"
        path.write_text(json.dumps(asdict(job), indent=2))
    
    def get(self, local_id: str) -> JobRecord:
        path = self.store_path / f"{local_id}.json"
        data = json.loads(path.read_text())
        return JobRecord(**data)
    
    def list_recent(self, limit: int = 20) -> list[JobRecord]:
        jobs = []
        for path in sorted(self.store_path.glob("*.json"), reverse=True)[:limit]:
            data = json.loads(path.read_text())
            jobs.append(JobRecord(**data))
        return jobs
    
    def update_status(self, local_id: str, status: str):
        job = self.get(local_id)
        job.status = status
        self.save(job)
```

---

## Phase 5: 모니터링

### 5.1 Job 상태 조회

```python
# myjob/monitor/status.py

@dataclass
class JobStatus:
    state: str              # PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, TIMEOUT
    elapsed_time: str
    node: Optional[str] = None
    reason: Optional[str] = None
    exit_code: Optional[str] = None

class JobMonitor:
    def __init__(self, ssh_client: SSHClient, job_store: JobStore):
        self.ssh = ssh_client
        self.store = job_store
    
    def get_status(self, local_id: str) -> JobStatus:
        job = self.store.get(local_id)
        
        # squeue로 확인 (큐에 있는 job)
        result = self.ssh.run(
            f"squeue -j {job.slurm_job_id} -h -o '%T|%M|%N|%R'",
            warn=True, hide=True
        )
        
        if result.ok and result.stdout.strip():
            parts = result.stdout.strip().split('|')
            return JobStatus(
                state=parts[0],
                elapsed_time=parts[1],
                node=parts[2] if parts[2] else None,
                reason=parts[3] if len(parts) > 3 else None,
            )
        
        # sacct로 확인 (완료된 job)
        result = self.ssh.run(
            f"sacct -j {job.slurm_job_id} -n -o State,ExitCode,Elapsed -P",
            hide=True
        )
        
        if result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            parts = lines[0].split('|')
            return JobStatus(
                state=parts[0],
                exit_code=parts[1],
                elapsed_time=parts[2],
            )
        
        return JobStatus(state="UNKNOWN", elapsed_time="")
```

### 5.2 로그 조회

```python
# myjob/monitor/logs.py

class LogViewer:
    def __init__(self, ssh_client: SSHClient, job_store: JobStore):
        self.ssh = ssh_client
        self.store = job_store
    
    def get_logs(self, local_id: str, stderr: bool = False, lines: int = 100) -> str:
        job = self.store.get(local_id)
        log_type = "stderr" if stderr else "stdout"
        log_path = f"{job.workspace}/logs/{log_type}_{job.slurm_job_id}.log"
        
        result = self.ssh.run(f"tail -n {lines} {log_path}", hide=True, warn=True)
        return result.stdout if result.ok else f"Log not found: {log_path}"
    
    def follow_logs(self, local_id: str, stderr: bool = False):
        job = self.store.get(local_id)
        log_type = "stderr" if stderr else "stdout"
        log_path = f"{job.workspace}/logs/{log_type}_{job.slurm_job_id}.log"
        
        self.ssh.run(f"tail -f {log_path}", pty=True)
```

### 5.3 작업 취소

```python
# myjob/monitor/cancel.py

class JobCanceller:
    def __init__(self, ssh_client: SSHClient, job_store: JobStore):
        self.ssh = ssh_client
        self.store = job_store
    
    def cancel(self, local_id: str, force: bool = False) -> bool:
        job = self.store.get(local_id)
        
        cmd = f"scancel {job.slurm_job_id}"
        if force:
            cmd = f"scancel --signal=KILL {job.slurm_job_id}"
        
        result = self.ssh.run(cmd, warn=True, hide=True)
        
        if result.ok:
            self.store.update_status(local_id, "CANCELLED")
            return True
        return False
```

### 5.4 노드/GPU 상태

```python
# myjob/monitor/nodes.py

@dataclass
class GPUInfo:
    gpu_type: str       # a100, v100 등
    total: int
    used: int
    free: int

@dataclass
class NodeInfo:
    name: str
    state: str          # idle, mixed, allocated, down
    partition: str
    cpus_total: int
    cpus_used: int
    memory_total: str
    gpu: Optional[GPUInfo]

class NodeMonitor:
    def __init__(self, ssh_client: SSHClient):
        self.ssh = ssh_client
    
    def get_nodes(self, partition: str = None) -> list[NodeInfo]:
        # 1. sinfo로 기본 정보
        cmd = "sinfo -N -h -o '%N|%P|%T|%C|%m'"
        if partition:
            cmd += f" -p {partition}"
        
        result = self.ssh.run(cmd, hide=True)
        nodes = {}
        
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            name, part, state, cpus, mem = line.split('|')
            cpu_parts = cpus.split('/')
            
            nodes[name] = NodeInfo(
                name=name,
                partition=part.rstrip('*'),
                state=state,
                cpus_total=int(cpu_parts[3]),
                cpus_used=int(cpu_parts[0]),
                memory_total=mem,
                gpu=None,
            )
        
        # 2. scontrol show node로 GPU 정보
        for node_name in nodes:
            nodes[node_name].gpu = self._get_gpu_info(node_name)
        
        return list(nodes.values())
    
    def _get_gpu_info(self, node_name: str) -> Optional[GPUInfo]:
        result = self.ssh.run(f"scontrol show node {node_name}", hide=True, warn=True)
        if not result.ok:
            return None
        
        output = result.stdout
        
        # Gres=gpu:a100:4 파싱
        gres_total = self._parse_field(output, "Gres")
        gres_used = self._parse_field(output, "GresUsed")
        
        if not gres_total or gres_total == "(null)":
            return None
        
        gpu_type, total = self._parse_gres(gres_total)
        _, used = self._parse_gres(gres_used) if gres_used else (None, 0)
        
        return GPUInfo(
            gpu_type=gpu_type,
            total=total,
            used=used,
            free=total - used,
        )
    
    def _parse_field(self, output: str, field: str) -> Optional[str]:
        for line in output.split('\n'):
            for part in line.split():
                if part.startswith(f"{field}="):
                    return part.split('=', 1)[1]
        return None
    
    def _parse_gres(self, gres_str: str) -> tuple[str, int]:
        """gpu:a100:4 → ("a100", 4)"""
        if not gres_str or gres_str == "(null)":
            return ("unknown", 0)
        
        gres_str = gres_str.split('(')[0]  # (IDX:...) 제거
        parts = gres_str.split(':')
        
        if len(parts) == 3:
            return (parts[1], int(parts[2]))
        elif len(parts) == 2:
            return ("gpu", int(parts[1]))
        
        return ("unknown", 0)
```

---

## CLI 인터페이스

### 명령어 목록

```bash
myjob submit                 # Job 제출
myjob status <job_id>        # 상태 확인
myjob logs <job_id>          # 로그 조회
myjob cancel <job_id>        # 작업 취소
myjob list                   # 제출한 작업 목록
myjob nodes                  # 클러스터 노드/GPU 상태
myjob init                   # 설정 파일 생성 (interactive)
```

### CLI 구현

```python
# myjob/cli/main.py

import typer
from typing import Optional, List

app = typer.Typer(name="myjob", help="Submit jobs to SLURM clusters")

@app.command()
def submit(
    config: Optional[str] = typer.Option(None, "-c", "--config"),
    host: Optional[str] = typer.Option(None, "-H", "--host"),
    partition: Optional[str] = typer.Option(None, "-p", "--partition"),
    account: Optional[str] = typer.Option(None, "-A", "--account"),
    gpus: Optional[int] = typer.Option(None, "-g", "--gpus"),
    cpus: Optional[int] = typer.Option(None, "-n", "--cpus"),
    memory: Optional[str] = typer.Option(None, "-m", "--memory"),
    time: Optional[str] = typer.Option(None, "-t", "--time"),
    name: Optional[str] = typer.Option(None, "--name"),
    force: bool = typer.Option(False, "--force", help="Ignore uncommitted changes"),
    wait: bool = typer.Option(False, "-w", "--wait", help="Wait for completion"),
    follow: bool = typer.Option(False, "-f", "--follow", help="Follow logs"),
    command: Optional[List[str]] = typer.Argument(None),
):
    """Submit a job to SLURM cluster"""
    pass

@app.command()
def status(
    job_id: str = typer.Argument(...),
    watch: bool = typer.Option(False, "-w", "--watch"),
):
    """Check job status"""
    pass

@app.command()
def logs(
    job_id: str = typer.Argument(...),
    follow: bool = typer.Option(False, "-f", "--follow"),
    stderr: bool = typer.Option(False, "-e", "--stderr"),
    lines: int = typer.Option(100, "-n", "--lines"),
):
    """View job logs"""
    pass

@app.command()
def cancel(
    job_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force"),
):
    """Cancel a job"""
    pass

@app.command(name="list")
def list_jobs(
    all: bool = typer.Option(False, "-a", "--all"),
    limit: int = typer.Option(20, "-n", "--limit"),
):
    """List submitted jobs"""
    pass

@app.command()
def nodes(
    partition: Optional[str] = typer.Option(None, "-p", "--partition"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
):
    """Show cluster node/GPU status"""
    pass

@app.command()
def init():
    """Initialize config file interactively"""
    pass

if __name__ == "__main__":
    app()
```

---

## 사용 예시

### Job 제출

```bash
# Config 파일 사용
$ myjob submit -c myjob.yaml

# CLI 오버라이드
$ myjob submit -c myjob.yaml --gpus 4 --time 48:00:00

# Config 없이
$ myjob submit -H cluster.example.com -p gpu -g 2 -m 16G -- python train.py
```

### 출력 예시

```
[1/5] 🔍 Validating configuration...
      ✓ Config valid

[2/5] 🔌 Connecting to cluster.example.com...
      ✓ Connected (SLURM 23.02)

[3/5] 📦 Syncing code via git...
      ⚠️  Warning: You have uncommitted changes (use --force to ignore)

$ git commit -am "experiment" && git push

$ myjob submit -c myjob.yaml

[3/5] 📦 Syncing code via git...
      Repository: git@github.com:user/project.git
      Branch: main
      Commit: a1b2c3d
      ✓ Cloned to remote workspace

[4/5] 🚀 Submitting job...
      ✓ Job submitted: SLURM_JOB_ID=12345678

[5/5] 📋 Job registered
      Local ID: a1b2c3

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Job submitted successfully!

Status:  myjob status a1b2c3
Logs:    myjob logs a1b2c3 -f
Cancel:  myjob cancel a1b2c3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 상태 확인

```bash
$ myjob status a1b2c3

Job: a1b2c3 (SLURM ID: 12345678)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Status:    RUNNING
Elapsed:   02:34:15
Node:      gpu-node-03
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Git:       main @ a1b2c3d
Command:   python train.py --epochs 100
```

### 노드 상태

```bash
$ myjob nodes

CLUSTER STATUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NODE          STATE      PARTITION   CPU (used/total)   GPU (free/total)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
gpu-node-01   mixed      gpu         24/64              2/4 (a100)
gpu-node-02   allocated  gpu         64/64              0/4 (a100)
gpu-node-03   idle       gpu         0/64               4/4 (a100)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SUMMARY
  Total GPUs: 12 (A100: 12)
  Free GPUs:  6 (A100: 6)
```

---

## 구현 우선순위

### Phase 1: MVP (최소 기능)
1. Config 로드 (myjob.yaml, secret.yaml)
2. SSH 연결 (fabric)
3. Git clone
4. sbatch 스크립트 생성 및 제출
5. 기본 status, logs 조회

### Phase 2: 완성도
6. cancel 기능
7. list 기능
8. nodes 기능
9. 에러 처리 개선
10. init 명령어

### Phase 3: 편의 기능
11. --wait, --follow 옵션
12. 이쁜 출력 (rich 라이브러리)
13. Tab completion
