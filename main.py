#!/usr/bin/env python3
"""Mac终端语音输入工具入口文件。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
src_path = PROJECT_ROOT / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from voice_entry import main


if __name__ == "__main__":
    main()
