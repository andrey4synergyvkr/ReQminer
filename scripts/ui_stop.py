from __future__ import annotations

import subprocess
import sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "8000"


def _run(cmd: list[str]) -> str:
    # вывод консольных утилит в cp866 - декодируем терпимо, нам нужны
    # только ASCII-токены (TCP, LISTENING, pid)
    return subprocess.run(cmd, capture_output=True).stdout.decode("utf-8", errors="replace")


def listening_pids(port: str) -> set[str]:
    """PID-ы процессов, слушающих порт (Windows netstat)."""
    pids: set[str] = set()
    for line in _run(["netstat", "-ano"]).splitlines():
        parts = line.split()
        # TCP  <local>  <remote>  LISTENING  <pid>
        if len(parts) == 5 and parts[0] == "TCP" and parts[3] == "LISTENING" \
                and parts[1].endswith(f":{port}"):
            pids.add(parts[4])
    return pids


def main() -> None:
    """Останавливает процессы на порту вместе с дочерними.

    Запуск: make stop [порт].
    Порт берётся из первого аргумента или 8000. taskkill /T нужен потому,
    что воркер uvicorn переживает мастер и продолжает держать порт.
    """
    pids = listening_pids(PORT)
    if not pids:
        print(f"Порт {PORT} свободен")
        return
    for pid in sorted(pids):
        _run(["taskkill", "/T", "/F", "/PID", pid])
        print(f"Остановлено дерево процессов {pid} (порт {PORT})")


if __name__ == "__main__":
    main()
