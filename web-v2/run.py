"""Start the single-user web application on the loopback interface."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

WEB = Path(__file__).resolve().parent
HOST = "127.0.0.1"
API_PORT = 8765
INITIAL_SOURCE = "EFA_WEB_INITIAL_SOURCE"


def select_local_source() -> Path | None:
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-Sta",
                    "-File",
                    str(WEB / "scripts" / "select-source.ps1"),
                ],
                stdout=subprocess.PIPE,
                encoding="utf-8",
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            filename = result.stdout.rstrip("\r\n")
            return Path(filename) if filename else None
        except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
            print(
                f"드래그앤드롭 창을 열지 못했습니다 ({exc}). 파일 선택 창을 엽니다.",
                file=sys.stderr,
                flush=True,
            )

    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError(
            "파일 선택 창에 Tcl/Tk가 필요합니다. --source로 파일을 지정하세요."
        ) from exc

    try:
        root = tk.Tk()
        try:
            root.attributes("-topmost", True)
            root.withdraw()
            filename = filedialog.askopenfilename(
                parent=root,
                title="분석할 Excel 고장이력 선택",
                filetypes=(("Excel 파일", ("*.xlsx", "*.xlsm")),),
            )
        finally:
            root.destroy()
    except tk.TclError as exc:
        raise RuntimeError("파일 선택 창을 열 수 없습니다. --source로 파일을 지정하세요.") from exc
    return Path(filename) if filename else None


def check_ports(*ports: int) -> None:
    for port in ports:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex((HOST, port)) == 0:
                raise RuntimeError(
                    f"{port} 포트가 사용 중입니다. 기존 웹 실행 창을 닫고 다시 실행하세요."
                )


def wait_for_http(url: str, process: subprocess.Popen, timeout: int | None = 90) -> None:
    deadline = time.monotonic() + timeout if timeout is not None else float("inf")
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"서버가 종료되었습니다 ({process.returncode}). {url}")
        try:
            with urlopen(url, timeout=2):
                return
        except (URLError, TimeoutError):
            time.sleep(0.35)
    raise RuntimeError(f"서버가 제한 시간 안에 응답하지 않았습니다. {url}")


def main() -> int:
    parser = argparse.ArgumentParser(description="설비 고장 분석기 웹 버전 실행")
    parser.add_argument("--dev", action="store_true", help="Next.js 개발 모드로 실행")
    parser.add_argument("--open", action="store_true", help="준비가 되면 기본 브라우저에서 열기")
    parser.add_argument("--port", type=int, default=3072)
    source_options = parser.add_mutually_exclusive_group()
    source_options.add_argument("--source", type=Path, help="시작할 때 지정한 Excel 파일 열기")
    source_options.add_argument(
        "--select-source", action="store_true", help="시작할 때 Excel 파일 열기 창 표시"
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.port == API_PORT:
        parser.error(f"웹 포트는 1~65535 사이에서 {API_PORT}를 제외하고 지정하세요.")

    frontend = WEB / "frontend"
    next_cli = frontend / "node_modules" / "next" / "dist" / "bin" / "next"
    node = shutil.which("node")
    if node is None or not next_cli.is_file():
        parser.error("Node.js를 설치하고 web-v2/frontend에서 npm ci를 실행하세요.")
    if not args.dev and not (frontend / ".next" / "BUILD_ID").is_file():
        parser.error("web-v2/frontend에서 npm run build를 실행하세요.")

    api_origin = f"http://{HOST}:{API_PORT}"
    web_origin = f"http://localhost:{args.port}"

    env = os.environ.copy()
    env.pop(INITIAL_SOURCE, None)
    env["EFA_BACKEND_ORIGIN"] = api_origin
    data_dir = Path(env.get("EFA_WEB_DATA_DIR") or WEB / ".data").expanduser().resolve()
    env["EFA_WEB_DATA_DIR"] = str(data_dir)
    env.setdefault("MPLCONFIGDIR", str(data_dir / "matplotlib"))
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("NEXT_TELEMETRY_DISABLED", "1")

    processes = []
    try:
        check_ports(args.port, API_PORT)
        source = args.source
        if args.select_source:
            source = select_local_source()
            if source is None:
                return 0

        api_env = env.copy()
        if source is not None:
            source = source.expanduser().absolute()
            if not source.is_file():
                raise RuntimeError("선택한 Excel 파일을 찾을 수 없습니다.")
            api_env[INITIAL_SOURCE] = str(source)
            print("선택한 Excel 파일을 읽는 중입니다.", flush=True)

        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app:app",
                "--app-dir",
                str(WEB / "backend"),
                "--host",
                HOST,
                "--port",
                str(API_PORT),
            ],
            cwd=WEB.parent,
            env=api_env,
        )
        processes.append(api)
        wait_for_http(f"{api_origin}/api/health", api, timeout=None if source else 90)

        web = subprocess.Popen(
            [
                node,
                str(next_cli),
                "dev" if args.dev else "start",
                "--hostname",
                HOST,
                "--port",
                str(args.port),
            ],
            cwd=frontend,
            env=env,
        )
        processes.append(web)
        wait_for_http(f"http://{HOST}:{args.port}/api/health", web)
        print(f"설비 고장 분석기 웹 버전 · {web_origin}", flush=True)
        if args.open:
            webbrowser.open(web_origin)

        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("웹 또는 API 서버가 종료되었습니다.")
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
