import re
from typing import Tuple, Optional

# Documented regular expression patterns matching automated search crawlers, tools, and scrapers
KNOWN_BOT_PATTERNS = [
    # Major search engines
    (r"googlebot", "Search Crawler: Googlebot"),
    (r"bingbot|bingpreview|msnbot", "Search Crawler: Bingbot"),
    (r"yandexbot|yandeximages", "Search Crawler: Yandex"),
    (r"baiduspider", "Search Crawler: Baidu"),
    (r"duckduckbot", "Search Crawler: DuckDuckGo"),
    (r"slurp", "Search Crawler: Yahoo! Slurp"),
    (r"sogou", "Search Crawler: Sogou"),
    (r"exabot", "Search Crawler: Exabot"),
    # SEO & social crawlers
    (r"ahrefsbot", "SEO Crawler: Ahrefs"),
    (r"semrushbot", "SEO Crawler: Semrush"),
    (r"mj12bot", "SEO Crawler: Majestic"),
    (r"facebookexternalhit|facebookcatalog", "Social Crawler: Facebook"),
    (r"twitterbot", "Social Crawler: Twitter"),
    (r"linkedinbot", "Social Crawler: LinkedIn"),
    (r"pinterestbot|pinterest", "Social Crawler: Pinterest"),
    (r"slackbot", "Social Crawler: Slack"),
    (r"discordbot", "Social Crawler: Discord"),
    (r"telegrambot", "Social Crawler: Telegram"),
    (r"whatsapp", "Social Crawler: WhatsApp"),
    # Automated scripts and command line tools
    (r"curl\/", "CLI Tool: curl"),
    (r"wget\/", "CLI Tool: wget"),
    (r"python-requests|aiohttp|urllib|httpx", "Script Client: Python HTTP"),
    (r"go-http-client", "Script Client: Go HTTP"),
    (r"postmanruntime", "API Tool: Postman"),
    (r"axios|node-fetch", "Script Client: Node.js"),
    (r"apache-httpclient|java\/", "Script Client: Java"),
    (r"phpcrawl|guzzlehttp", "Script Client: PHP"),
    (r"headlesschrome", "Automated Browser: HeadlessChrome"),
    (r"phantomjs", "Automated Browser: PhantomJS"),
    (r"selenium|webdriver|puppeteer|playwright", "Automation Framework"),
    (r"lighthouse|chrome-lighthouse", "Audit Tool: Lighthouse"),
    (r"uptimebot|uptimerobot|statuscake|pingdom", "Uptime Monitor"),
    (r"bytespider", "Crawler: ByteSpider"),
    (r"petalbot", "Crawler: PetalBot"),
    (r"crawler|spider|robot|scraper|archive\.org_bot", "Generic Bot/Crawler"),
]

COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), reason) for p, reason in KNOWN_BOT_PATTERNS]


def classify_traffic(user_agent: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Classify whether an incoming request matches known bot / automated agent patterns.
    Note: Rapid refreshes from a normal browser are NOT classified as bots.
    User-Agent detection cannot catch all stealth or custom bots, which is documented.
    
    Returns:
        (is_bot: bool, reason: Optional[str])
    """
    if not user_agent or not user_agent.strip():
        return True, "Missing User-Agent header"

    ua = user_agent.strip()

    # Suspiciously short or generic User-Agent
    if len(ua) < 8 and ua.lower() in ("test", "bot", "python", "http"):
        return True, f"Suspicious short User-Agent: {ua}"

    for pattern, reason in COMPILED_PATTERNS:
        if pattern.search(ua):
            return True, reason

    return False, None
