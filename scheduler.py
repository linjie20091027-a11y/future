"""NewsPusher 定时调度器 — 持续运行，每天 12:00 和 20:00 自动抓取并推送新闻。

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

from main import run_once, BASE_DIR

load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)

PUSH_TIMES = ["12:00", "20:00"]


def show_banner():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   NewsPusher · 科技&金融资讯推送    ║")
    print("  ║   推送时间: 每天 12:00 / 20:00      ║")
    print("  ║   按 Ctrl+C 停止                      ║")
    print("  ╚══════════════════════════════════════╝")
    print()


def next_push_time() -> str:
    now = datetime.now()
    for t in PUSH_TIMES:
        h, m = map(int, t.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target > now:
            return target.strftime("%Y-%m-%d %H:%M")
    # 今天已过最后一班，返回明天第一班
    h, m = map(int, PUSH_TIMES[0].split(":"))
    next_day = now.replace(hour=h, minute=m, second=0, microsecond=0)
    from datetime import timedelta
    next_day += timedelta(days=1)
    return next_day.strftime("%Y-%m-%d %H:%M")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_once()
        return

    show_banner()

    logger.info("启动后立即执行首次抓取...")
    run_once()

    for t in PUSH_TIMES:
        schedule.every().day.at(t).do(run_once)
        logger.info("已注册定时任务: 每天 %s", t)

    logger.info("调度器已启动，下次推送: %s", next_push_time())

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("用户中断，调度器已停止")


if __name__ == "__main__":
    main()
