#!/usr/bin/env python3
"""Western Slope Local News Bot - Location-Based Filtering"""
import feedparser
import httpx
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Set, Optional
from selectolax.parser import HTMLParser

WEBHOOKS = {
    'KJCT8': [
        "YOUR_KJCT8_WEBHOOK_URL_HERE"
    ],
    'Western Slope Now': [
        "YOUR_WESTERN_SLOPE_NOW_WEBHOOK_URL_HERE"
    ],
    'Daily Sentinel': [
        "YOUR_DAILY_SENTINEL_WEBHOOK_URL_HERE"
    ]
}

KJCT8_RSS = "https://www.kjct8.com/arc/outboundfeeds/rss/?outputType=xml"
WESTERN_SLOPE_NOW_RSS = "https://www.westernslopenow.com/feed/"
DAILY_SENTINEL_URL = "https://www.gjsentinel.com/search/?f=rss&t=article&l=100&s=start_time&sd=desc&c=news/western_colorado"
SEEN_FILE = Path(__file__).parent / "seen_items.json"

COLORS = {'KJCT8': 0x3745e0, 'Daily Sentinel': 0xd3c68e, 'Western Slope Now': 0x2596be}
MAX_ARTICLES_PER_SOURCE = 10

# Western Colorado locations to check for
WESTERN_CO_LOCATIONS = {
    'grand junction', 'mesa county', 'western slope', 'western colorado',
    'palisade', 'fruita', 'clifton', 'montrose', 'delta', 'telluride',
    'durango', 'cortez', 'ouray', 'ridgway', 'cedaredge', 'paonia'
}

class LocalNewsBot:
    def __init__(self):
        self.client = httpx.Client(
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
            timeout=30.0, follow_redirects=True
        )
        self.seen_links = self._load_seen_links()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()
    
    def _load_seen_links(self) -> Set[str]:
        try:
            if SEEN_FILE.exists():
                with open(SEEN_FILE, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'keys' in data:
                        return {key.split('|', 1)[1] for key in data['keys'] if '|' in key}
            return set()
        except:
            return set()
    
    def _save_seen_link(self, link: str, source: str):
        try:
            try:
                with open(SEEN_FILE, 'r') as f:
                    data = json.load(f)
                    keys = data.get('keys', [])
            except:
                keys = []
            
            key = f"{source}|{link}"
            if key not in keys:
                keys.append(key)
                with open(SEEN_FILE, 'w') as f:
                    json.dump({'keys': keys}, f, indent=2)
                self.seen_links.add(link)
        except:
            pass
    
    def _extract_image_from_rss(self, entry) -> Optional[str]:  # type: ignore
        """Extract image from RSS feed entry"""
        try:
            if hasattr(entry, 'media_content') and entry.media_content:
                for media in entry.media_content:
                    if isinstance(media, dict) and media.get('type', '').startswith('image/'):
                        url = media.get('url', '')
                        if url:
                            return url
            
            if hasattr(entry, 'enclosures') and entry.enclosures:
                for enclosure in entry.enclosures:
                    if isinstance(enclosure, dict) and enclosure.get('type', '').startswith('image/'):
                        url = enclosure.get('href', '')
                        if url:
                            return url
            
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                if isinstance(entry.media_thumbnail, list) and entry.media_thumbnail:
                    return entry.media_thumbnail[0].get('url', '')
                elif isinstance(entry.media_thumbnail, dict):
                    return entry.media_thumbnail.get('url', '')
            
            return None
        except:
            return None
    
    def _extract_image_from_page(self, url: str) -> Optional[str]:
        """Extract image from article page"""
        try:
            response = self.client.get(url, timeout=10)
            if response.status_code != 200:
                return None
            
            tree = HTMLParser(response.text)
            
            og_image = tree.css_first('meta[property="og:image"]')
            if og_image and 'content' in og_image.attributes:
                return og_image.attributes['content']
            
            twitter_image = tree.css_first('meta[name="twitter:image"]')
            if twitter_image and 'content' in twitter_image.attributes:
                return twitter_image.attributes['content']
            
            return None
        except:
            return None
    
    def _is_local(self, title: str, summary: str, tags: List[str], source: str) -> bool:
        """Check if article is about Western Colorado"""
        # Western Slope Now properly tags their local news
        if source == 'Western Slope Now':
            local_tags = {'local', 'local news', 'living local'}
            for tag in tags:
                if any(lt in tag.lower() for lt in local_tags):
                    return True
            return False
        
        # For KJCT8 and Daily Sentinel, check if Western CO locations are mentioned
        content = f"{title} {summary}".lower()
        
        # Must mention a Western Colorado location
        if any(location in content for location in WESTERN_CO_LOCATIONS):
            return True
        
        return False
    
    def _fetch_rss_news(self, url: str, source: str) -> List[Dict]:  # type: ignore
        try:
            response = self.client.get(url)
            feed = feedparser.parse(response.content)  # type: ignore
            if not feed or not getattr(feed, "entries", None):
                return []
            
            articles = []
            for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:  # type: ignore
                link = getattr(entry, 'link', '')
                if not link or link in self.seen_links:
                    if link in self.seen_links:
                        break
                    continue
                
                title = getattr(entry, 'title', 'No Title')
                snippet = getattr(entry, 'summary', '') or getattr(entry, 'description', '')
                
                # Extract tags
                tags = []
                if hasattr(entry, 'tags'):
                    tags = [tag.term for tag in entry.tags if hasattr(tag, 'term')]
                
                # Clean snippet
                if snippet:
                    try:
                        tree = HTMLParser(snippet)
                        snippet = tree.text(separator=' ', strip=True)
                    except:
                        snippet = re.sub(r'<[^>]+>', '', snippet)
                        snippet = re.sub(r'\s+', ' ', snippet).strip()
                
                # Filter for local content
                if not self._is_local(title, snippet, tags, source):
                    continue
                
                if len(snippet) > 2000:
                    snippet = snippet[:1997] + "..."
                
                # Get image
                image_url = self._extract_image_from_rss(entry)
                if not image_url:
                    image_url = self._extract_image_from_page(link)
                
                articles.append({
                    'title': title,
                    'link': link,
                    'description': snippet,
                    'image_url': image_url,
                    'source': source
                })
            
            return articles
        except:
            return []
    
    def _post_to_discord(self, article: Dict) -> bool:
        try:
            embed = {
                "title": article['title'],
                "url": article['link'],
                "description": article['description'],
                "color": COLORS.get(article['source'], 0x3498db),
            }
            
            if article.get('image_url'):
                embed["image"] = {"url": article['image_url']}
            
            webhook_urls = WEBHOOKS.get(article['source'])
            if not webhook_urls:
                return False
            
            success = True
            for webhook_url in webhook_urls:
                try:
                    payload = {"username": article['source'], "embeds": [embed]}
                    response = self.client.post(webhook_url, json=payload, timeout=10)
                    response.raise_for_status()
                except:
                    success = False
            
            if success:
                print(f"✓ [{article['source']}] {article['title']}")
            return success
        except:
            return False
    
    def run(self):
        try:
            kjct8_articles = self._fetch_rss_news(KJCT8_RSS, 'KJCT8')
            western_slope_articles = self._fetch_rss_news(WESTERN_SLOPE_NOW_RSS, 'Western Slope Now')
            sentinel_articles = self._fetch_rss_news(DAILY_SENTINEL_URL, 'Daily Sentinel')
            
            all_articles = kjct8_articles + western_slope_articles + sentinel_articles
            
            # Reverse for backfill (oldest to newest)
            all_articles.reverse()
            
            if not all_articles:
                print("No new local articles")
                return 0
            
            posted = 0
            for article in all_articles:
                if self._post_to_discord(article):
                    self._save_seen_link(article['link'], article['source'])
                    posted += 1
            
            print(f"Posted {posted}/{len(all_articles)} local articles (oldest to newest)")
            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1

def main():
    try:
        with LocalNewsBot() as bot:
            return bot.run()
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Fatal: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
