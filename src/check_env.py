from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    S3_BACKEND, S3_ENDPOINT, S3_BUCKET, VACANCIES_KEY, CURATED_KEY,
    get_s3_client,
)

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"
_rows: list[tuple[str, str, str]] = []

def check(name: str, status: str, detail: str = "") -> None:
    _rows.append((name, status, detail))

def check_python() -> None:
    version = sys.version_info
    text = ".".join(map(str, version[:3]))
    status = OK if version >= (3, 10) else FAIL
    check("Python >= 3.10", status, f"{text} ({sys.executable})")

def check_packages() -> None:
    for module, label in [
        ("boto3", "boto3"),
        ("duckdb", "duckdb"),
        ("psutil", "psutil"),
        ("matplotlib", "matplotlib"),
    ]:
        spec = importlib.util.find_spec(module)
        if spec is None:
            check(f"package {label}", FAIL, "не установлен")
            continue
        try:
            mod = __import__(module)
            check(f"package {label}", OK, getattr(mod, "__version__", "installed"))
        except Exception as exc:
            check(f"package {label}", FAIL, f"{type(exc).__name__}: {exc}")

def check_endpoint() -> None:
    if S3_BACKEND != "boto3":
        check("S3 endpoint", WARN, f"backend={S3_BACKEND}, сеть не проверяется")
        return
    url = urlparse(S3_ENDPOINT)
    host = url.hostname or "localhost"
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=3):
            check(f"S3 endpoint {S3_ENDPOINT}", OK, f"TCP {host}:{port} доступен")
    except OSError as exc:
        check(f"S3 endpoint {S3_ENDPOINT}", FAIL,
              f"TCP {host}:{port}: {exc} — запустите: docker compose up -d")

def check_storage() -> None:
    try:
        cli = get_s3_client()
    except Exception as exc:
        check("S3 client", FAIL, f"{type(exc).__name__}: {exc}")
        return
    check("S3 client", OK, f"backend={S3_BACKEND}, bucket={S3_BUCKET}")

    info = cli.head_object(VACANCIES_KEY)
    if info is None:
        check(f"object s3://{S3_BUCKET}/{VACANCIES_KEY}", FAIL,
              "не найден — выполните: python src/upload.py")
    else:
        status = OK if info.size > 0 else FAIL
        check(f"object s3://{S3_BUCKET}/{VACANCIES_KEY}", status,
              f"{info.size:,} B ({info.size / 2**20:.1f} MiB), etag={info.etag}")

    curated = cli.head_object(CURATED_KEY)
    if curated is None:
        check(f"object {CURATED_KEY}", WARN,
              "ещё не создан (python src/optimized_mapreduce.py prepare)")
    else:
        check(f"object {CURATED_KEY}", OK,
              f"{curated.size:,} B ({curated.size / 2**20:.2f} MiB)")

def check_local_dirs() -> None:
    for name in ("report/logs", "report/images", "data"):
        path = Path(name)
        if path.exists():
            check(f"dir {name}", OK, "есть")
        else:
            path.mkdir(parents=True, exist_ok=True)
            check(f"dir {name}", WARN, "создана")

def check_docker() -> None:
    """Best-effort container check; Docker may be unavailable in CI."""
    try:
        out = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}} {{.Status}}"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        check("docker compose", WARN, f"не удалось проверить: {exc}")
        return
    if out.returncode != 0:
        check("docker compose", WARN, (out.stderr or "docker недоступен").strip()[:160])
        return
    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    if not lines:
        check("docker compose", WARN, "контейнеры не запущены (docker compose up -d)")
        return
    healthy = [ln for ln in lines if "healthy" in ln.lower() or "up" in ln.lower()]
    check("docker compose", OK if healthy else WARN,
          " | ".join(lines)[:300])

def main() -> int:
    check_python()
    check_packages()
    check_endpoint()
    check_storage()
    check_local_dirs()
    check_docker()

    width = max(len(name) for name, _, _ in _rows) + 2
    print("\n" + "=" * (width + 60))
    print("ENVIRONMENT CHECK — HW3 DevOps pipeline")
    print("=" * (width + 60))
    for name, status, detail in _rows:
        print(f"  [{status:4}] {name:<{width}} {detail}")
    failures = [r for r in _rows if r[1] == FAIL]
    warnings = [r for r in _rows if r[1] == WARN]
    print("-" * (width + 60))
    print(f"  OK: {sum(1 for r in _rows if r[1] == OK)}  "
          f"WARN: {len(warnings)}  FAIL: {len(failures)}")
    if failures:
        print("\n  Исправьте пункты FAIL перед запуском пайплайна.")
        return 1
    print("\n  Окружение готово к запуску: python src/run_all.py")
    return 0

if __name__ == "__main__":
    sys.exit(main())
