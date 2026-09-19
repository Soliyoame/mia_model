"""安全入口：冻结或执行 v6.3 precision-cascade eligibility 分波扫描。"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.eligibility_scan import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
