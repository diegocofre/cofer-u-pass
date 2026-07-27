from __future__ import annotations

import subprocess
import sys


def run(*cmd: str) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    run(sys.executable, "-m", "compileall", "-q", "src")
    run(sys.executable, "-m", "pytest", "-q", "-m", "not smoke")
    print("Deterministic checks passed. Live provider smoke tests remain supervised release gates.")


if __name__ == "__main__":
    main()
