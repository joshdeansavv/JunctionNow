#!/usr/bin/env python3
"""GJ News Feed Bot - With Images and Descriptions"""
import feedparser
import httpx
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Set, Optional
from selectolax.parser import HTMLParser

WEBHOOKS = {
    'Mesa County': [
        "YOUR_MESA_COUNTY_WEBHOOK_URL_HERE"
    ],
    'City of Grand Junction': [
        "YOUR_CITY_OF_GJ_WEBHOOK_URL_HERE"
    ]
}
GJ_CITY_RSS = "https://www.gjcity.org/RSSFeed.aspx?ModID=1&CID=City-of-Grand-Junction-News"
MESA_COUNTY_URL = "https://www.mesacounty.us/news"
SEEN_FILE = Path(__file__).parent / "seen_items.json"

COLOR_GJ_CITY = 0x1f8b4c
COLOR_MESA_COUNTY = 0x3498db
MAX_ARTICLES_PER_SOURCE = 5

class GJNewsBot:
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
    
    def _extract_image(self, url: str) -> Optional[str]:
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
    
    def _fetch_gj_city_news(self) -> List[Dict]:
        try:
            response = self.client.get(GJ_CITY_RSS)
            feed = feedparser.parse(response.content)
            articles = []
            
            for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
                link = entry.get('link', '')
                if not link or link in self.seen_links:
                    if link in self.seen_links:
                        break
                    continue
                
                title = entry.get('title', 'No Title')
                description = entry.get('description', '') or entry.get('summary', '')
                
                if description:
                    try:
                        tree = HTMLParser(description)
                        description = tree.text(separator=' ', strip=True)
                    except:
                        description = re.sub(r'<[^>]+>', '', description)
                        description = re.sub(r'\s+', ' ', description).strip()
                
                if len(description) > 2000:
                    description = description[:1997] + "..."
                
                image_url = self._extract_image(link)
                
                articles.append({
                    'title': title,
                    'link': link,
                    'description': description,
                    'image_url': image_url,
                    'source': 'City of Grand Junction'
                })
            
            return articles
        except:
            return []
    
    def _fetch_mesa_county_news(self) -> List[Dict]:
        try:
            response = self.client.get(MESA_COUNTY_URL)
            tree = HTMLParser(response.text)
            articles = []
            
            listing = tree.css_first('section.content-listing')
            if not listing:
                return []
            
            news_cards = listing.css('div.horizontal_card')[:MAX_ARTICLES_PER_SOURCE]
            
            for card in news_cards:
                title_elem = card.css_first('h3.card__heading a')
                if not title_elem:
                    continue
                
                link = title_elem.attributes.get('href', '')
                if link.startswith('/'):
                    link = f"https://www.mesacounty.us{link}"
                
                if link in self.seen_links:
                    break
                
                title = title_elem.text(strip=True)
                description = ""
                # Try div.field-summary first (new structure), then p.card__body
                desc_elem = card.css_first('div.field-summary')
                if not desc_elem:
                    desc_elem = card.css_first('p.card__body')
                if desc_elem:
                    description = desc_elem.text(strip=True)
                
                if len(description) > 2000:
                    description = description[:1997] + "..."
                
                image_url = None
                img_elem = card.css_first('img.image')
                if img_elem and 'src' in img_elem.attributes:
                    image_url = img_elem.attributes['src']
                    if image_url.startswith('/'):
                        image_url = f"https://www.mesacounty.us{image_url}"
                
                if not image_url:
                    image_url = self._extract_image(link)
                
                articles.append({
                    'title': title,
                    'link': link,
                    'description': description,
                    'image_url': image_url,
                    'source': 'Mesa County'
                })
            
            return articles
        except:
            return []
    
    def _post_to_discord(self, article: Dict) -> bool:
        try:
            username = "GJ City News" if article['source'] == 'City of Grand Junction' else "Mesa County News"
            color = COLOR_GJ_CITY if article['source'] == 'City of Grand Junction' else COLOR_MESA_COUNTY
            
            embed = {
                "title": article['title'],
                "url": article['link'],
                "color": color,
            }
            
            if article.get('description'):
                embed["description"] = article['description']
            
            if article.get('image_url'):
                embed["image"] = {"url": article['image_url']}
            
            webhook_urls = WEBHOOKS.get(article['source'])
            if not webhook_urls:
                return False
            
            success = True
            for webhook_url in webhook_urls:
                try:
                    payload = {"username": username, "embeds": [embed]}
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
            gj_articles = self._fetch_gj_city_news()
            mesa_articles = self._fetch_mesa_county_news()
            all_articles = gj_articles + mesa_articles
            
            # Reverse for backfill (oldest to newest)
            all_articles.reverse()
            
            if not all_articles:
                print("No new articles")
                return 0
            
            posted = 0
            for article in all_articles:
                if self._post_to_discord(article):
                    self._save_seen_link(article['link'], article['source'])
                    posted += 1
            
            print(f"Posted {posted}/{len(all_articles)} articles (oldest to newest)")
            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1

def main():
    try:
        with GJNewsBot() as bot:
            return bot.run()
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Fatal: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
