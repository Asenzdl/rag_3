import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.app import main


__all__ = ["main"]


# ============================================================
# 标准入口守卫
# ============================================================
if __name__ == "__main__":
      main()