#!/usr/bin/env python3
"""CrimeWatch Mesa County Bot - Discord Feed"""
import httpx
import json
import re
import sys
import time
from pathlib import Path
from typing import List, Dict, Set, Optional
from selectolax.parser import HTMLParser
from datetime import datetime

WEBHOOK_URL = "YOUR_DISCORD_WEBHOOK_URL_HERE"
CRIMEWATCH_URL = "https://crimewatch.net/us/co/mesa"
SEEN_FILE = Path(__file__).parent / "seen_items.json"

COLOR = 0xFF0000  # Red color for crime alerts
MAX_ITEMS = 15

class CrimeWatchBot:
    def __init__(self):
        self.client = httpx.Client(
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            },
            timeout=30.0,
            follow_redirects=True
        )
        self.seen_items = self._load_seen_items()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()
    
    def _load_seen_items(self) -> Set[str]:
        try:
            if SEEN_FILE.exists():
                with open(SEEN_FILE, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'items' in data:
                        return set(data['items'])
            return set()
        except:
            return set()
    
    def _save_seen_item(self, item_id: str):
        try:
            try:
                with open(SEEN_FILE, 'r') as f:
                    data = json.load(f)
                    items = data.get('items', [])
            except:
                items = []
            
            if item_id not in items:
                items.append(item_id)
                with open(SEEN_FILE, 'w') as f:
                    json.dump({'items': items}, f, indent=2)
                self.seen_items.add(item_id)
        except:
            pass
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        return text
    
    def _extract_date(self, date_text: str) -> Optional[str]:
        """Extract and format date from text"""
        try:
            # Look for patterns like "Oct 28, 2025"
            date_match = re.search(r'([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})', date_text)
            if date_match:
                return date_match.group(0)
            return None
        except:
            return None
    
    def _scrape_news_feed(self) -> List[Dict]:
        """Scrape news feed from CrimeWatch Mesa County"""
        try:
            response = self.client.get(CRIMEWATCH_URL)
            if response.status_code != 200:
                print(f"Failed to fetch page: {response.status_code}")
                return []
            
            tree = HTMLParser(response.text)
            items = []
            
            # Find all news items - they're in div.news-single-card elements
            news_items = tree.css('div.news-single-card')
            
            if not news_items:
                print("No news items found with selector 'div.news-single-card'")
                return []
            
            # Parse each news item
            for item in news_items[:MAX_ITEMS]:
                try:
                    # Extract title from h3 a inside div.single-news-title
                    title_elem = item.css_first('div.single-news-title h3 a')
                    if not title_elem:
                        continue
                    
                    title = self._clean_text(title_elem.text())
                    if not title or len(title) < 5:
                        continue
                    
                    # Extract link
                    if 'href' not in title_elem.attributes:
                        continue
                    
                    link = title_elem.attributes['href']
                    
                    # Make link absolute
                    if link.startswith('/'):
                        link = f"https://crimewatch.net{link}"
                    elif not link.startswith('http'):
                        link = f"https://crimewatch.net/{link}"
                    
                    # Create unique ID from link
                    item_id = link
                    
                    if item_id in self.seen_items:
                        continue
                    
                    # Extract description - it's the last div.single-news-subtitle with actual content
                    desc_elems = item.css('div.single-news-subtitle')
                    description = ""
                    if desc_elems:
                        # The last one usually has the description text
                        for desc_elem in desc_elems:
                            text = self._clean_text(desc_elem.text())
                            # Skip if it's just "Mesa County Sheriff's Office" or similar short text
                            if len(text) > 50:
                                description = text
                                break
                        
                        if len(description) > 2000:
                            description = description[:1997] + "..."
                    
                    # Extract image from img inside div.img-wrapper
                    image_url = None
                    img_elem = item.css_first('div.img-wrapper img[src]')
                    if img_elem and 'src' in img_elem.attributes:
                        image_url = img_elem.attributes['src']
                        # Make image URL absolute
                        if image_url.startswith('/'):
                            image_url = f"https://crimewatch.net{image_url}"
                        elif not image_url.startswith('http'):
                            image_url = f"https://crimewatch.net/{image_url}"
                    
                    # Extract date from div.single-news-date
                    date_elem = item.css_first('div.single-news-date')
                    date_str = None
                    if date_elem:
                        date_text = self._clean_text(date_elem.text())
                        date_str = date_text if date_text else None
                    
                    items.append({
                        'id': item_id,
                        'title': title,
                        'link': link,
                        'description': description,
                        'image_url': image_url,
                        'date': date_str
                    })
                
                except Exception as e:
                    print(f"Error parsing item: {e}")
                    continue
            
            return items
        
        except Exception as e:
            print(f"Error scraping CrimeWatch: {e}")
            return []
    
    def _post_to_discord(self, item: Dict) -> bool:
        try:
            embed = {
                "title": item['title'],
                "url": item['link'],
                "color": COLOR,
            }
            
            if item.get('description'):
                embed["description"] = item['description']
            
            if item.get('image_url'):
                embed["image"] = {"url": item['image_url']}
            
            if item.get('date'):
                embed["footer"] = {"text": item['date']}
            
            payload = {
                "username": "CrimeWatch Mesa County",
                "embeds": [embed]
            }
            
            response = self.client.post(WEBHOOK_URL, json=payload, timeout=10)
            response.raise_for_status()
            
            print(f"✓ {item['title']}")
            return True
        
        except Exception as e:
            print(f"✗ Failed to post: {e}")
            return False
    
    def run(self):
        try:
            items = self._scrape_news_feed()
            
            if not items:
                print("No new items found")
                return 0
            
            # Reverse for backfill (oldest to newest)
            items.reverse()
            
            posted = 0
            for item in items:
                if self._post_to_discord(item):
                    self._save_seen_item(item['id'])
                    posted += 1
                    # Add delay to avoid rate limiting
                    if posted < len(items):
                        time.sleep(2)
            
            print(f"Posted {posted}/{len(items)} items")
            return 0
        
        except Exception as e:
            print(f"Error: {e}")
            return 1

def main():
    try:
        with CrimeWatchBot() as bot:
            return bot.run()
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Fatal: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

