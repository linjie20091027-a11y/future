"""NewsPusher 定时调度器 — 持续运行，按设定间隔自动抓取并推送新闻。

使用方法:
    python scheduler.py              # 启动定时调度（持续运行）
    python scheduler.py --once       # 立即执行一次

也可配合 Windows 任务计划程序定时调用:
    python main.py
"""

import sys
import time
import logging
from datetime import datetime

import schedule
from dotenv import load_dotenv

from main import run_once, PUSH_INTERVAL_HOURS, BASE_DIR

load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)


def show_banner():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   NewsPusher · 科技&金融资讯推送    ║")
    print(f"  ║   推送间隔: 每 {PUSH_INTERVAL_HOURS} 小时           ║")
    print("  ║   按 Ctrl+C 停止                      ║")
    print("  ╚══════════════════════════════════════╝")
    print()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_once()
        return

    show_banner()

    # 启动后立即执行一次
    logger.info("启动后立即执行首次抓取...")
    run_once()

    # 设置定时任务
    schedule.every(PUSH_INTERVAL_HOURS).hours.do(run_once)

    logger.info("调度器已启动，下次执行时间: %s", 
                datetime.now().strftime("%H:%M") + f" (+{PUSH_INTERVAL_HOURS}h)")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("用户中断，调度器已停止")


if __name__ == "__main__":
    main()
