"""Run an isolated browser-verification stack without touching development data."""

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from backend.app.config import BROWSER_VERIFICATION_ENVIRONMENT, Settings

BACKEND_PORT = 8876
FRONTEND_PORT = 5174


def verification_database_from_environment() -> Path:
    raw_path = os.getenv("DACHIK_DATABASE_PATH")
    if not raw_path:
        raise ValueError("Set DACHIK_DATABASE_PATH to an explicit temporary SQLite path")
    path = Path(raw_path).expanduser().resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if path != temporary_root and temporary_root not in path.parents:
        raise ValueError(f"Browser-verification database must be under {temporary_root}")
    Settings(database_path=path, runtime_environment=BROWSER_VERIFICATION_ENVIRONMENT)
    return path


def dispose_database(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dispose",
        action="store_true",
        help="delete the isolated SQLite files after both servers stop",
    )
    args = parser.parse_args()
    try:
        database_path = verification_database_from_environment()
    except ValueError as exc:
        parser.error(str(exc))

    environment = os.environ.copy()
    environment.update(
        {
            "DACHIK_DATABASE_PATH": str(database_path),
            "DACHIK_ENVIRONMENT": BROWSER_VERIFICATION_ENVIRONMENT,
            "DACHIK_CORS_ORIGINS": f"http://127.0.0.1:{FRONTEND_PORT}",
            "VITE_API_BASE_URL": f"http://127.0.0.1:{BACKEND_PORT}",
            "VITE_DACHIK_ENVIRONMENT": BROWSER_VERIFICATION_ENVIRONMENT,
        }
    )
    root = Path(__file__).resolve().parents[1]
    print(f"Environment: {BROWSER_VERIFICATION_ENVIRONMENT}")
    print(f"Temporary database: {database_path}")
    print(f"Frontend: http://127.0.0.1:{FRONTEND_PORT}")
    print(f"Backend: http://127.0.0.1:{BACKEND_PORT}")
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(BACKEND_PORT),
            ],
            cwd=root,
            env=environment,
        ),
        subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(FRONTEND_PORT), "--strictPort"],
            cwd=root / "frontend",
            env=environment,
        ),
    ]
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.2)
        return next(
            process.returncode for process in processes if process.returncode is not None
        )
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
        if args.dispose:
            dispose_database(database_path)
            print(f"Disposed browser-verification database: {database_path}")


if __name__ == "__main__":
    raise SystemExit(main())
