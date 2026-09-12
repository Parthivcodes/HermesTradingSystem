import os, sys
from pathlib import Path

root = Path(__file__).resolve().parent / "hermes-agent-main"
sys.path.insert(0, str(root))
os.chdir(root)

from trading_engine.__main__ import main

if __name__ == "__main__":
    main()
