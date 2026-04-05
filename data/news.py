"""Real-time news feed via Finnhub API."""

import finnhub
from datetime import datetime, timedelta

from config import FINNHUB_API_KEY

# ---------------------------------------------------------------------------
# Source quality scoring for news prioritization
# ---------------------------------------------------------------------------
PREFERRED_SOURCES = ["Reuters", "Bloomberg", "CNBC", "Dow Jones", "WSJ",
                     "Wall Street Journal", "Financial Times", "Barron's", "MarketWatch"]
DEPRIORITIZED = ["Yahoo", "Motley Fool", "Seeking Alpha", "Benzinga"]

# Filter out clickbait/listicle headlines
SPAM_KEYWORDS = [
    "best stocks to", "top stocks to", "stocks to buy", "buy now",
    "top picks", "must-buy", "don't miss", "millionaire", "retire early",
    "get rich", "best investment", "hot stocks", "penny stocks",
    "stocks to watch today", "best stocks for", "top investment",
    "should you buy", "is it time to buy", "stocks under $",
]


def _is_spam(headline):
    """Return True if headline looks like clickbait."""
    h = headline.lower()
    return any(kw in h for kw in SPAM_KEYWORDS)


def _source_score(source):
    source_lower = source.lower()
    for i, pref in enumerate(PREFERRED_SOURCES):
        if pref.lower() in source_lower:
            return 100 - i  # higher = better
    for dep in DEPRIORITIZED:
        if dep.lower() in source_lower:
            return 10
    return 50  # unknown source gets middle priority

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = finnhub.Client(api_key=FINNHUB_API_KEY)
    return _client


def fetch_market_news(category="general", limit=20):
    """Fetch general market news.

    Args:
        category: 'general', 'forex', 'crypto', 'merger'
        limit: max articles to return
    Returns: list of {headline, source, url, datetime, summary}
    """
    try:
        client = _get_client()
        articles = client.general_news(category, min_id=0)
        results = []
        for a in articles[:limit]:
            ts = a.get("datetime", 0)
            dt = datetime.fromtimestamp(ts) if ts else None
            age = _format_age(dt) if dt else ""
            results.append({
                "headline": a.get("headline", ""),
                "source": a.get("source", ""),
                "url": a.get("url", "#"),
                "datetime": dt,
                "age": age,
                "summary": a.get("summary", ""),
            })
        results = [r for r in results if not _is_spam(r.get("headline", ""))]
        results.sort(key=lambda x: _source_score(x.get("source", "")), reverse=True)
        return results
    except Exception as e:
        print(f"  Warning: Finnhub market news failed: {e}")
        return []


def fetch_company_news(symbol, days_back=3, limit=5):
    """Fetch news for a specific company.

    Args:
        symbol: ticker symbol
        days_back: how many days of news to fetch
        limit: max articles
    Returns: list of {headline, source, url, datetime, summary}
    """
    try:
        client = _get_client()
        today = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        articles = client.company_news(symbol, _from=from_date, to=today)
        results = []
        for a in articles[:limit]:
            ts = a.get("datetime", 0)
            dt = datetime.fromtimestamp(ts) if ts else None
            age = _format_age(dt) if dt else ""
            results.append({
                "headline": a.get("headline", ""),
                "source": a.get("source", ""),
                "url": a.get("url", "#"),
                "datetime": dt,
                "age": age,
                "summary": a.get("summary", ""),
            })
        results = [r for r in results if not _is_spam(r.get("headline", ""))]
        results.sort(key=lambda x: _source_score(x.get("source", "")), reverse=True)
        return results
    except Exception as e:
        print(f"  Warning: Finnhub company news for {symbol} failed: {e}")
        return []


def _format_age(dt):
    """Format datetime as relative age string: '2h ago', '15m ago', '1d ago'."""
    if dt is None:
        return ""
    delta = datetime.now() - dt
    minutes = int(delta.total_seconds() / 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"
