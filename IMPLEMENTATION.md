# myjob CLI 구현 요약

## 개요

원격 SLURM 클러스터에서 job을 제출하고 관리하는 CLI 도구를 구현했습니다. Python 기반으로 typer, fabric, pydantic 등을 활용하여 Phase 1 MVP를 완성했습니다.

## 구현된 기능

### CLI 명령어

| 명령어 | 설명 |
|--------|------|
| `myjob init` | 설정 파일 생성 (interactive/minimal 모드) |
| `myjob submit` | SLURM 클러스터에 job 제출 |
| `myjob status <job_id>` | job 상태 확인 (squeue/sacct) |
| `myjob logs <job_id>` | job 로그 조회 (`-f`로 follow 가능) |
| `myjob list` | 최근 제출한 job 목록 |
| `myjob cancel <job_id>` | 실행 중인 job 취소 |

### 주요 옵션

```bash
# submit 옵션
myjob submit -c config.yaml  # 설정 파일 지정
myjob submit --dry-run       # 실제 제출 없이 확인
myjob submit -g 2            # GPU 개수 오버라이드
myjob submit -t 8:00:00      # 시간 제한 오버라이드

# logs 옵션
myjob logs <job_id> -f       # 실시간 로그 follow
myjob logs <job_id> -n 100   # 마지막 100줄
myjob logs <job_id> -e       # stderr 출력
myjob logs <job_id> -b       # stdout/stderr 모두 출력
```

## 프로젝트 구조

```
myjob/
├── pyproject.toml              # 패키지 설정 및 의존성
├── README.md                   # 사용 가이드
├── .gitignore
├── myjob/
│   ├── __init__.py             # 버전 정보
│   ├── cli/
│   │   ├── main.py             # Typer CLI 앱 정의
│   │   └── commands/
│   │       ├── init.py         # myjob init 명령
│   │       ├── submit.py       # myjob submit 명령
│   │       ├── status.py       # myjob status/list/cancel 명령
│   │       └── logs.py         # myjob logs 명령
│   ├── core/
│   │   ├── models.py           # Pydantic 모델 (JobConfig 등)
│   │   ├── config.py           # YAML 설정 로드/병합
│   │   └── job_id.py           # 6자리 로컬 job ID 생성
│   ├── transport/
│   │   ├── ssh.py              # Fabric 기반 SSH 클라이언트
│   │   └── git_sync.py         # Git 저장소 동기화
│   ├── backend/
│   │   └── slurm.py            # sbatch 스크립트 생성/제출
│   ├── monitor/
│   │   ├── status.py           # squeue/sacct 상태 조회
│   │   └── logs.py             # 로그 파일 조회/follow
│   └── storage/
│       └── job_store.py        # ~/.myjob/jobs/ 로컬 저장소
└── tests/
    └── __init__.py
```

## 설정 파일

### myjob.yaml (프로젝트별 설정)

```yaml
name: my-experiment

connection:
  host: cluster.example.com
  user: myuser

slurm:
  partition: gpu
  account: my-account

resources:
  nodes: 1
  cpus_per_task: 4
  gpus: 1
  memory: 32G
  time: "4:00:00"

execution:
  command: python train.py
  modules:
    - cuda/11.8
    - python/3.10
  setup_commands:
    - pip install -r requirements.txt

git:
  auto_detect: true  # 로컬 git 정보 자동 감지

workspace: ~/myjob-workspace
```

### secret.yaml (민감 정보, .gitignore에 포함)

```yaml
connection:
  host: cluster.example.com
  user: myuser
  key_file: ~/.ssh/id_rsa

env_vars:
  WANDB_API_KEY: your-api-key
  HF_TOKEN: your-token
```

## 설정 우선순위

1. CLI 인자 (최우선)
2. myjob.yaml
3. secret.yaml
4. 기본값

## 의존성

- **typer**: CLI 프레임워크
- **fabric**: SSH 연결 및 원격 명령 실행
- **pydantic**: 설정 검증 및 모델 정의
- **pyyaml**: YAML 파싱
- **rich**: 터미널 출력 포맷팅

## 설치 및 실행

```bash
# 가상환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate

# 패키지 설치
pip install -e .

# 설정 파일 생성
myjob init

# job 제출 (dry-run)
myjob submit --dry-run

# 실제 제출
myjob submit
```

## 데이터 저장

- **로컬 job 기록**: `~/.myjob/jobs/<local_id>.json`
- **원격 작업 디렉토리**: `~/myjob-workspace/<job_name>-<local_id>/`
- **로그 파일**: `<workspace>/logs/`

## 향후 개선 사항 (Phase 2+)

- [ ] job 템플릿 지원
- [ ] 멀티 클러스터 관리
- [ ] job 의존성 (DAG) 지원
- [ ] 실시간 모니터링 대시보드
- [ ] Slack/이메일 알림
- [ ] 결과 파일 자동 동기화
