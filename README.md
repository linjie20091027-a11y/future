# NewsPusher — 科技&金融资讯实时推送

定时抓取 GitHub 前沿、国内科技圈、全球金融圈的最新资讯，格式化为 HTML 邮件推送到 QQ 邮箱。

## 三个板块

| 板块 | 来源 | 说明 |
|------|------|------|
| **GitHub 前沿** | GitHub Trending + Hacker News | 热门开源项目、技术趋势 |
| **国内科技** | 36氪、少数派、IT之家 | 互联网创投、效率工具、IT资讯 |
| **全球金融** | 雪球热门、FT中文网 | 投资热点、全球财经要闻 |

> 邮件顶部有目录标签，点击即可锚点跳转到对应板块。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 .env（复制模板填入真实信息）
cp .env.example .env

# 3. 测试单次运行
python main.py

# 4. 启动定时推送（默认每3小时）
python scheduler.py
```

## 配置说明 `.env`

```env
# QQ邮箱（必填）
SENDER_EMAIL=你的QQ号@qq.com
SMTP_AUTH_CODE=QQ邮箱授权码（16位，非QQ密码）
RECEIVER_EMAIL=接收邮箱

# 推送间隔（小时）
PUSH_INTERVAL_HOURS=3

# AI 翻译（可选，GitHub描述转中文）
# 支持 DeepSeek / OpenAI 兼容接口
AI_API_KEY=你的API Key
AI_API_URL=https://api.deepseek.com/v1/chat/completions
AI_MODEL=deepseek-chat
```

**授权码获取**：QQ邮箱 → 设置 → 账户 → POP3/SMTP服务 → 开启 → 生成授权码

## 自定义新闻源

编辑 `main.py` 中的 `GITHUB_SOURCES` / `TECH_SOURCES` / `FINANCE_SOURCES`：

```python
GITHUB_SOURCES = [
    ("trending", "GitHub Trending"),
    ("https://hnrss.org/frontpage", "Hacker News"),
]
```

格式：`("RSS地址", "显示名称")`，`"trending"` 为 GitHub Trending 页面解析。

## 定时运行

- **前台持续运行**：`python scheduler.py`
- **Windows 任务计划程序**：触发器每3小时执行 `python main.py`

## 邮件效果

- 三栏卡片布局，顶部目录标签锚点跳转
- 自动去重，同一条新闻不重复推送
- GitHub 项目显示语言标签 + AI 中文简介（需配置 Key）
