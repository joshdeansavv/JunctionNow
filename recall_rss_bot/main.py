#!/usr/bin/env python3
"""FDA Recalls Bot - Minimal Version"""
import httpx
import os
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Optional
from selectolax.parser import HTMLParser
import extruct
import dateparser

DISCORD_WEBHOOKS = [
    "YOUR_DISCORD_WEBHOOK_URL_HERE"
]
FDA_RECALLS_URL = "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts"
SEEN_FILE = Path(__file__).parent / "seen_items.json"

FDA_NAV_LINKS = [
    '/recall-resources', '/enforcement-reports', '/industry-guidance-recalls',
    '/major-product-recalls', '/additional-information-about-recalls',
    '/recalls-market-withdrawals-safety-alerts#',
]

MAX_RECALLS_PER_RUN = 10
EMBED_COLOR = 0x007CBA

class RecallBot:
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
        except Exception as e:
            print(f"Error saving: {e}")
    
    def _extract_image(self, article_url: str) -> Optional[str]:
        try:
            response = self.client.get(article_url, timeout=10)
            if response.status_code != 200:
                return None
            
            tree = HTMLParser(response.text)
            image_candidates = []
            
            # Try structured data first
            try:
                structured_data = extruct.extract(response.text, base_url=article_url)
                for item in structured_data.get('json-ld', []):
                    if isinstance(item, dict) and 'image' in item:
                        image = item['image']
                        if isinstance(image, dict):
                            image_url = image.get('url', '')
                        elif isinstance(image, list) and image:
                            image_url = image[0] if isinstance(image[0], str) else image[0].get('url', '')
                        else:
                            image_url = str(image)
                        if image_url and 'fda-social' not in image_url.lower():
                            image_candidates.append(image_url)
            except:
                pass
            
            # Look for product images in article content
            skip_patterns = ['logo', 'icon', 'seal', 'badge', 'usa-banner', 'us_flag', 'fda_logo', 'fda-social']
            
            for area_selector in ['article', 'main', 'div.field--name-body', 'div.content']:
                area = tree.css_first(area_selector)
                if area:
                    for img in area.css('img'):
                        if 'src' in img.attributes:
                            src = img.attributes['src']
                            if not any(skip in src.lower() for skip in skip_patterns):
                                if src.startswith('/'):
                                    src = f"https://www.fda.gov{src}"
                                image_candidates.append(src)
                                break
                    if image_candidates:
                        break
            
            # Try Open Graph (but skip FDA social graphic)
            if not image_candidates:
                og_image = tree.css_first('meta[property="og:image"]')
                if og_image and 'content' in og_image.attributes:
                    og_url = og_image.attributes['content']
                    if 'fda-social' not in og_url.lower():
                        image_candidates.append(og_url)
            
            # Return first valid image
            for img_url in image_candidates:
                if any(ext in img_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                    return img_url
            
            return None
        except:
            return None
    
    def _fetch_fda_recalls(self) -> List[Dict]:
        try:
            response = self.client.get(FDA_RECALLS_URL)
            if response.status_code != 200:
                return []
            
            tree = HTMLParser(response.text)
            all_links = []
            
            for link in tree.css('a[href*="/safety/recalls-market-withdrawals-safety-alerts/"]'):
                href = link.attributes.get('href', '')
                if href and href.startswith('/safety/recalls-market-withdrawals-safety-alerts/'):
                    all_links.append(href)
            
            unique_links = list(dict.fromkeys(all_links))
            recalls = []
            
            for link_path in unique_links:
                if any(nav_link in link_path for nav_link in FDA_NAV_LINKS):
                    continue
                
                full_url = f"https://www.fda.gov{link_path}"
                if full_url in self.seen_links:
                    # Already processed this recall; skip but keep scanning others
                    continue
                
                try:
                    recall_response = self.client.get(full_url, timeout=10)
                    if recall_response.status_code != 200:
                        continue
                    
                    recall_tree = HTMLParser(recall_response.text)
                    title_elem = recall_tree.css_first('h1')
                    title = title_elem.text(strip=True) if title_elem else link_path.split('/')[-1].replace('-', ' ').title()
                    
                    def get_dd_sibling(dt_elem):
                        next_elem = dt_elem.next
                        while next_elem and next_elem.tag != 'dd':
                            next_elem = next_elem.next
                        return next_elem if next_elem and next_elem.tag == 'dd' else None
                    
                    brand_names = []
                    reason = ""
                    company_names = []
                    product_desc = ""
                    
                    for dt in recall_tree.css('dt'):
                        dt_text = dt.text()
                        dd = get_dd_sibling(dt)
                        if not dd:
                            continue
                        
                        if 'Brand Name' in dt_text:
                            items = dd.css('div.field--item')
                            if items:
                                brand_names = [item.text(strip=True) for item in items if item.text(strip=True)]
                            else:
                                brands_text = dd.text(strip=True)
                                brand_names = [b.strip() for b in re.split(r',|\n', brands_text) if b.strip()]
                        elif 'Reason for Announcement' in dt_text:
                            items = dd.css('div.field--item')
                            if items:
                                for item in items:
                                    item_text = item.text(strip=True)
                                    if item_text and len(item_text) > 10:
                                        reason = item_text
                                        break
                            if not reason:
                                reason = dd.text(strip=True)
                        elif 'Company Name' in dt_text:
                            companies_text = dd.text(strip=True)
                            company_names = [c.strip() for c in re.split(r',|\n', companies_text) if c.strip()]
                        elif 'Product Description' in dt_text:
                            items = dd.css('div.field--item')
                            if items:
                                product_desc = ' '.join([item.text(strip=True) for item in items if item.text(strip=True)])
                            else:
                                product_desc = dd.text(strip=True)
                    
                    image_url = self._extract_image(full_url)
                    
                    recalls.append({
                        'title': title,
                        'link': full_url,
                        'brand_names': brand_names,
                        'reason': reason,
                        'company_names': company_names,
                        'product_description': product_desc,
                        'image_url': image_url,
                        'source': 'FDA Recalls'
                    })
                    
                    if len(recalls) >= MAX_RECALLS_PER_RUN:
                        break
                except:
                    continue
            
            return recalls
        except:
            return []
    
    def _post_to_discord(self, recall: Dict) -> bool:
        try:
            # Allow safe testing without posting to Discord
            if os.getenv('DRY_RUN') == '1':
                print(f"[DRY RUN] Would post: {recall.get('title', recall.get('link', 'Unknown'))}")
                return False
            parts = []
            parts.append(f"**[{recall['title']}](<{recall['link']}>)**")
            parts.append("")
            
            sentence = []
            if recall.get('product_description'):
                sentence.append(recall['product_description'])
            
            if recall.get('company_names'):
                company_str = ' and '.join(recall['company_names'][:2]) if len(recall['company_names']) > 1 else recall['company_names'][0]
                if sentence:
                    sentence.append(f"from {company_str}")
                else:
                    sentence.append(company_str)
            
            if recall.get('reason'):
                if sentence:
                    sentence.append(f"is being recalled due to {recall['reason'].lower()}")
                else:
                    sentence.append(f"Recall due to {recall['reason'].lower()}")
            else:
                if sentence:
                    sentence.append("is being recalled")
            
            if sentence:
                parts.append(' '.join(sentence) + ".")
            
            if recall.get('brand_names'):
                if len(recall['brand_names']) == 1:
                    parts.append(f"Brand name: {recall['brand_names'][0]}.")
                else:
                    brands_str = ', '.join(recall['brand_names'][:3])
                    if len(recall['brand_names']) > 3:
                        brands_str += f", and {len(recall['brand_names']) - 3} more"
                    parts.append(f"Brand names: {brands_str}.")
            
            description = '\n'.join(parts)
            if len(description) > 2000:
                description = description[:1997] + "..."
            
            embed = {"description": description, "color": EMBED_COLOR}
            if recall.get('image_url'):
                embed["image"] = {"url": recall['image_url']}
            
            success = True
            for webhook in DISCORD_WEBHOOKS:
                try:
                    response = self.client.post(webhook, json={"embeds": [embed]}, timeout=10)
                    response.raise_for_status()
                except:
                    success = False
            
            if success:
                print(f"✓ {recall['title']}")
            return success
        except:
            return False
    
    def run(self):
        try:
            recalls = self._fetch_fda_recalls()
            if not recalls:
                print("No new recalls")
                return 0
            
            # Reverse for backfill (oldest to newest)
            recalls.reverse()
            
            posted = 0
            for recall in recalls:
                if self._post_to_discord(recall):
                    self._save_seen_link(recall['link'], recall['source'])
                    posted += 1
            
            print(f"Posted {posted}/{len(recalls)} recalls (oldest to newest)")
            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1

def main():
    try:
        with RecallBot() as bot:
            return bot.run()
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Fatal: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
