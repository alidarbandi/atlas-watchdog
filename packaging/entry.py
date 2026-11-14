"""PyInstaller entry point; normal state is always outside this bundle."""
from atlas_watchdog.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
