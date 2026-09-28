"""生成样例与真值语料的脚本入口（与 py -X utf8 -m siteguard.cli datagen 等价）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from siteguard.datagen import generate_all  # noqa: E402

if __name__ == "__main__":
    print(generate_all(force="--force" in sys.argv))
