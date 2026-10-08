"""情绪板命令兼容入口；仅预览原生完成结果，旧文本样本生成已退役。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_moodboard_host import main

if __name__ == "__main__":
    main()
