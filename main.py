import os
import re
import json
import logging
import smtplib
from html import unescape
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import feedparser
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / "sent_cache.json"
LOG_FILE = BASE_DIR / "news_pusher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

load_dotenv(BASE_DIR / ".env")

SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SMTP_AUTH_CODE = os.getenv("SMTP_AUTH_CODE", "")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "")
PUSH_INTERVAL_HOURS = int(os.getenv("PUSH_INTERVAL_HOURS", "3"))
MAX_ARTICLES_PER_SOURCE = int(os.getenv("MAX_ARTICLES_PER_SOURCE", "8"))

# AI 翻译（将 GitHub 描述转为简洁中文）
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_URL = os.getenv("AI_API_URL", "https://api.deepseek.com/v1/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")

# ─── 三板块新闻源 ───────────────────────────────────────────

GITHUB_SOURCES = [
    ("trending", "GitHub Trending"),   # 特殊处理：页面解析
    ("https://hnrss.org/frontpage", "Hacker News"),
]

TECH_SOURCES = [
    ("https://36kr.com/feed", "36氪"),
    ("https://sspai.com/feed", "少数派"),
    ("https://www.ithome.com/rss/", "IT之家"),
]

FINANCE_SOURCES = [
    ("https://xueqiu.com/hots/topic/rss", "雪球热门"),
    ("https://www.ftchinese.com/rss/news", "FT中文网"),
]

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}
REQUEST_TIMEOUT = 15


# ─── 缓存管理 ───────────────────────────────────────────────

def load_sent_cache() -> set:
    if not CACHE_FILE.exists():
        return set()
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            cache = set(data)
            if len(cache) > 2000:
                cache = set(list(cache)[-1500:])
            return cache
    except Exception:
        pass
    return set()


def save_sent_cache(urls: set):
    CACHE_FILE.write_text(json.dumps(list(urls), ensure_ascii=False), encoding="utf-8")


# ─── 抓取模块 ───────────────────────────────────────────────

def fetch_rss(url: str, source_name: str) -> list[dict]:
    articles = []
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except requests.RequestException as e:
        logger.warning("请求失败 [%s]: %s", source_name, e)
        return articles
    except Exception as e:
        logger.warning("解析失败 [%s]: %s", source_name, e)
        return articles

    if feed.bozo and not feed.entries:
        logger.warning("RSS格式异常 [%s]", source_name)
        return articles

    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        if summary:
            summary = unescape(summary)
            summary = re.sub(r"<[^>]+>", "", summary)[:150].strip()
        articles.append({
            "title": title,
            "link": link,
            "source": source_name,
            "summary": summary,
        })
    return articles


def translate_batch(texts: list[str]) -> list[str]:
    """批量翻译英文技术描述为简洁中文（需配置 AI_API_KEY）"""
    if not texts or not AI_API_KEY:
        return texts
    prompt = (
        "将以下GitHub项目英文简介翻译为简洁中文（20字以内），"
        "保留技术术语和专有名词，不要添加解释，每个翻译用换行分隔：\n"
        + "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    )
    try:
        resp = requests.post(
            AI_API_URL,
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": "你是GitHub项目简介翻译助手。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # 拆分行，过滤掉编号前缀
        result = []
        for line in content.strip().split("\n"):
            line = re.sub(r"^\d+\.\s*", "", line).strip()
            if line:
                result.append(line)
        # 确保长度匹配
        while len(result) < len(texts):
            result.append("")
        return result[: len(texts)]
    except Exception as e:
        logger.warning("AI翻译失败: %s", e)
        return texts


def fetch_github_trending() -> list[dict]:
    articles = []
    try:
        resp = requests.get(
            "https://github.com/trending",
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning("GitHub Trending 请求失败: %s", e)
        return articles

    # 提取仓库链接：/owner/repo 格式（排除 /trending/, /sponsors/ 等）
    repo_links = re.findall(
        r'href="(/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+)"',
        html,
    )
    seen = set()
    repos = []
    for link in repo_links:
        if link in seen:
            continue
        parts = link.strip("/").split("/")
        if len(parts) != 2:
            continue
        if parts[0] in ("trending", "sponsors", "login", "settings",
                         "notifications", "explore", "topics", "marketplace"):
            continue
        seen.add(link)
        repos.append(link)

    # 提取描述
    desc_map = {}
    desc_blocks = re.findall(
        r'href="(/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+)".*?<p class="[^"]*col-9[^"]*"[^>]*>\s*(.*?)\s*</p>',
        html,
        re.DOTALL,
    )
    for href, desc in desc_blocks:
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        desc_map[href] = desc

    # 提取语言和stars
    lang_map = {}
    lang_blocks = re.findall(
        r'href="(/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+)".*?<span itemprop="programmingLanguage">([^<]*)</span>',
        html,
    )
    for href, lang in lang_blocks:
        lang_map[href] = lang.strip()

    # 收集需要翻译的描述
    descs_to_translate = {}
    for link in repos[:MAX_ARTICLES_PER_SOURCE]:
        desc = desc_map.get(link, "")
        if desc and AI_API_KEY:
            descs_to_translate[link] = desc

    # 批量翻译（如果配置了AI Key）
    if descs_to_translate:
        translated = translate_batch(list(descs_to_translate.values()))
        for link, cn_desc in zip(descs_to_translate.keys(), translated):
            if cn_desc:
                desc_map[link] = cn_desc

    for link in repos[:MAX_ARTICLES_PER_SOURCE]:
        name = link.strip("/")
        desc = desc_map.get(link, "")
        lang = lang_map.get(link, "")
        extra = f" [{lang}]" if lang else ""
        title = name + extra
        articles.append({
            "title": title,
            "link": f"https://github.com{link}",
            "source": "GitHub Trending",
            "summary": desc,
        })

    return articles


def fetch_all_news() -> list[dict]:
    all_articles = []

    # GitHub 板块
    all_articles.extend(fetch_github_trending())
    for url, name in GITHUB_SOURCES:
        if url == "trending":
            continue  # 已特殊处理
        arts = fetch_rss(url, name)
        all_articles.extend(arts[:MAX_ARTICLES_PER_SOURCE])

    # 国内科技板块
    for url, name in TECH_SOURCES:
        arts = fetch_rss(url, name)
        all_articles.extend(arts[:MAX_ARTICLES_PER_SOURCE])

    # 全球金融板块
    for url, name in FINANCE_SOURCES:
        arts = fetch_rss(url, name)
        all_articles.extend(arts[:MAX_ARTICLES_PER_SOURCE])

    return all_articles


# ─── 分类 ───────────────────────────────────────────────────

def classify_article(article: dict) -> str:
    source = article["source"]
    github_names = {n for _, n in GITHUB_SOURCES} | {"GitHub Trending"}
    tech_names = {n for _, n in TECH_SOURCES}
    finance_names = {n for _, n in FINANCE_SOURCES}
    if source in github_names:
        return "github"
    if source in tech_names:
        return "tech"
    if source in finance_names:
        return "finance"
    return "tech"


# ─── 去重 ───────────────────────────────────────────────────

def deduplicate(articles: list[dict]) -> list[dict]:
    cache = load_sent_cache()
    new_articles = []
    seen_titles = set()
    for a in articles:
        url = a["link"]
        title = a["title"][:80]
        if url in cache or title in seen_titles:
            continue
        new_articles.append(a)
        seen_titles.add(title)
        cache.add(url)
    save_sent_cache(cache)
    return new_articles


# ─── HTML 邮件模板 ──────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{
    margin: 0; padding: 16px; background: #f0f2f5;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Microsoft YaHei", "Helvetica Neue", sans-serif;
  }}
  .container {{ max-width: 640px; margin: 0 auto; }}
  /* ── 顶部 ── */
  .top {{
    background: #fff; border-radius: 8px; padding: 18px 20px 12px;
    margin-bottom: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.04);
  }}
  .top h1 {{ margin: 0; font-size: 20px; color: #1a1a2e; }}
  .top .sub {{ font-size: 12px; color: #999; margin-top: 2px; }}
  /* ── 目录标签 ── */
  .nav {{ display: flex; gap: 8px; margin-top: 10px; }}
  .nav a {{
    text-decoration: none; font-size: 12px; padding: 4px 14px;
    border-radius: 14px; color: #fff; font-weight: 600;
  }}
  .nav .n-github {{ background: #24292f; }}
  .nav .n-tech {{ background: #3b82f6; }}
  .nav .n-finance {{ background: #f59e0b; }}
  /* ── 板块卡片 ── */
  .card {{
    background: #fff; border-radius: 8px; padding: 14px 18px;
    margin-bottom: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.04);
  }}
  .card-head {{
    display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
  }}
  .card-head .dot {{
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
  }}
  .card-head .dot.github {{ background: #24292f; }}
  .card-head .dot.tech {{ background: #3b82f6; }}
  .card-head .dot.finance {{ background: #f59e0b; }}
  .card-head h2 {{ margin: 0; font-size: 15px; color: #1a1a2e; }}
  .card-head .count {{
    font-size: 12px; color: #999; font-weight: 400;
  }}
  /* ── 条目 ── */
  .item {{
    padding: 8px 0; border-bottom: 1px solid #f0f0f0;
  }}
  .item:last-child {{ border-bottom: none; }}
  .item .row {{
    display: flex; align-items: baseline; gap: 6px;
  }}
  .item a {{
    font-size: 14px; font-weight: 600; color: #1a1a2e;
    text-decoration: none; flex: 1; line-height: 1.4;
  }}
  .item a:hover {{ color: #3b82f6; text-decoration: underline; }}
  .item .tag {{
    font-size: 10px; padding: 1px 6px; border-radius: 3px;
    color: #fff; white-space: nowrap; flex-shrink: 0;
  }}
  .item .tag.github-src {{ background: #57606a; }}
  .item .tag.tech-src {{ background: #3b82f6; }}
  .item .tag.finance-src {{ background: #f59e0b; }}
  .item .desc {{
    font-size: 12px; color: #888; margin-top: 2px; line-height: 1.4;
  }}
  .empty {{ text-align: center; color: #bbb; padding: 16px; font-size: 13px; }}
  /* ── 底部 ── */
  .foot {{
    text-align: center; font-size: 11px; color: #bbb; padding: 12px;
  }}
</style>
</head>
<body>
<div class="container">

<!-- 顶部 -->
<div class="top">
  <h1>科技 & 金融 · 每日速递</h1>
  <div class="sub">{date_str} · 下次推送 {next_push} 后</div>
  <div class="nav">
    <a href="#github" class="n-github">GitHub 前沿</a>
    <a href="#tech" class="n-tech">国内科技</a>
    <a href="#finance" class="n-finance">全球金融</a>
  </div>
</div>

{content}

<div class="foot">NewsPusher 自动生成 · 去重推送</div>
</div>
</body>
</html>"""


def build_html(
    github_articles: list[dict],
    tech_articles: list[dict],
    finance_articles: list[dict],
) -> str:
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日 %H:%M")
    next_push = f"{PUSH_INTERVAL_HOURS} 小时"

    def render_section(anchor, label, css_class, src_class, articles):
        if not articles:
            return (
                f'<div class="card" id="{anchor}">'
                f'<div class="card-head">'
                f'<div class="dot {css_class}"></div>'
                f'<h2>{label}</h2>'
                f'</div>'
                f'<div class="empty">暂无新内容</div>'
                f'</div>'
            )
        items = []
        for a in articles:
            tag_html = f'<span class="tag {src_class}">{a["source"]}</span>' if a["source"] else ""
            desc_html = f'<div class="desc">{a["summary"]}</div>' if a.get("summary") else ""
            items.append(
                f'<div class="item">'
                f'<div class="row"><a href="{a["link"]}" target="_blank">{a["title"]}</a>{tag_html}</div>'
                f'{desc_html}'
                f'</div>'
            )
        joined = "\n".join(items)
        return (
            f'<div class="card" id="{anchor}">'
            f'<div class="card-head">'
            f'<div class="dot {css_class}"></div>'
            f'<h2>{label}</h2>'
            f'<span class="count">{len(articles)} 条</span>'
            f'</div>'
            f'{joined}'
            f'</div>'
        )

    sections = [
        render_section("github", "GitHub 前沿", "github", "github-src", github_articles),
        render_section("tech", "国内科技", "tech", "tech-src", tech_articles),
        render_section("finance", "全球金融", "finance", "finance-src", finance_articles),
    ]
    content = "\n".join(sections)

    return HTML_TEMPLATE.format(
        date_str=date_str,
        next_push=next_push,
        content=content,
    )


# ─── 邮件发送 ───────────────────────────────────────────────

def send_email(html_content: str) -> bool:
    if not SENDER_EMAIL or not SMTP_AUTH_CODE:
        logger.error("未配置邮箱信息，请检查 .env 文件")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL or SENDER_EMAIL
    msg["Subject"] = f"GitHub前沿 / 科技 / 金融 · {datetime.now().strftime('%m/%d %H:%M')}"
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=20)
        server.login(SENDER_EMAIL, SMTP_AUTH_CODE)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL or SENDER_EMAIL], msg.as_string())
        server.quit()
        logger.info("邮件发送成功 -> %s", RECEIVER_EMAIL or SENDER_EMAIL)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP认证失败，请确认授权码正确")
    except smtplib.SMTPConnectError:
        logger.error("无法连接QQ邮箱SMTP服务器，请检查网络")
    except Exception as e:
        logger.error("邮件发送异常: %s", e)
    return False


# ─── 主流程 ─────────────────────────────────────────────────

def run_once():
    logger.info("=" * 50)
    logger.info("开始抓取新闻...")
    articles = fetch_all_news()
    logger.info("共抓取 %d 条（去重前）", len(articles))

    new_articles = deduplicate(articles)
    logger.info("去重后 %d 条新内容", len(new_articles))

    if not new_articles:
        logger.info("无新内容，跳过发送")
        return

    github_articles = [a for a in new_articles if classify_article(a) == "github"]
    tech_articles = [a for a in new_articles if classify_article(a) == "tech"]
    finance_articles = [a for a in new_articles if classify_article(a) == "finance"]

    logger.info(
        "GitHub: %d 条, 科技: %d 条, 金融: %d 条",
        len(github_articles), len(tech_articles), len(finance_articles),
    )

    html = build_html(github_articles, tech_articles, finance_articles)
    send_email(html)


if __name__ == "__main__":
    run_once()
