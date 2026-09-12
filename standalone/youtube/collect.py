"""Run from the repository root after installation."""
from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["run", "--config", "config.yaml", "--platform", "youtube"]))
