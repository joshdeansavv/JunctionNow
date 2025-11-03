#!/usr/bin/env python3
"""Mesa County Coroner Facebook Monitor - Stealth Version
Uses undetected-chromedriver to bypass Facebook's bot detection.
"""
import json
import sys
import time
import random
import hashlib
from pathlib import Path
from typing import List, Dict, Set
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import httpx

# Force unbuffered output for proper logging
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None
sys.stderr.reconfigure(line_buffering=True) if hasattr(sys.stderr, 'reconfigure') else None

WEBHOOK_URL = "YOUR_DISCORD_WEBHOOK_URL_HERE"
# Simple page URL
FACEBOOK_PAGE_URL = "https://www.facebook.com/MesaCountyCoronersOffice"

COOKIE_FILE = Path(__file__).parent / "fb_cookies.json"
SEEN_FILE = Path(__file__).parent / "seen_items.json"

COLOR = 0xFF6B35

class FacebookStealthBot:
    def __init__(self):
        self.seen_items = self._load_seen_items()
        self.driver = None
    
    def _load_seen_items(self) -> Set[str]:
        if SEEN_FILE.exists():
            with open(SEEN_FILE, 'r') as f:
                data = json.load(f)
                return set(data.get('items', []))
        return set()
    
    def _save_seen_item(self, item_id: str):
        self.seen_items.add(item_id)
        items = list(self.seen_items)
        # Keep only last 100 items
        if len(items) > 100:
            items = items[-100:]
            self.seen_items = set(items)
        # Always save to file after adding new item
        with open(SEEN_FILE, 'w') as f:
            json.dump({'items': items}, f, indent=2)
    
    def _init_driver(self, headless=True):
        """Initialize undetected Chrome driver"""
        print("Initializing stealth browser...")
        
        options = uc.ChromeOptions()
        
        if headless:
            # Use headless mode for server
            options.add_argument('--headless=new')
        
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        # Desktop viewport
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-features=IsolateOrigins,site-per-process')
        
        # Initialize undetected chromedriver
        self.driver = uc.Chrome(options=options, version_main=142, use_subprocess=True)
        
        print("Browser initialized successfully")
    
    def _load_cookies(self):
        """Load cookies from file"""
        if COOKIE_FILE.exists():
            print("Loading saved cookies...")
            with open(COOKIE_FILE, 'r') as f:
                cookies = json.load(f)
                
            # Navigate to Facebook first
            self.driver.get("https://www.facebook.com")
            time.sleep(2)
            
            # Add cookies
            for cookie in cookies:
                try:
                    # Remove domain dot prefix if present
                    if 'domain' in cookie and cookie['domain'].startswith('.'):
                        cookie['domain'] = cookie['domain'][1:]
                    self.driver.add_cookie(cookie)
                except Exception as e:
                    print(f"  Warning: Could not add cookie {cookie.get('name')}: {e}")
            
            print("Cookies loaded successfully")
            return True
        return False
    
    def _manual_login_required(self):
        """Display instructions for manual login"""
        print("\n" + "="*60)
        print("⚠️  MANUAL LOGIN REQUIRED")
        print("="*60)
        print("\nYou need to login on your LOCAL machine first:")
        print("1. Run the fb_login_helper.py script on your Mac")
        print("2. Login to Facebook in the browser")
        print("3. Transfer fb_cookies.json to this server")
        print("\nSee FINAL_SOLUTION.md for detailed instructions.")
        print("="*60 + "\n")
        sys.exit(1)
    
    def _human_like_scroll(self):
        """Scroll like a human"""
        # Random scroll amounts
        scroll_amount = random.randint(300, 800)
        self.driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        time.sleep(random.uniform(1.5, 3.0))
    
    def _scrape_posts(self) -> List[Dict]:
        """Scrape posts from Facebook page"""
        try:
            # Check if we have cookies
            if not COOKIE_FILE.exists():
                print("⚠️  No cookies found. This requires a Facebook account.")
                print("Run the fb_login_helper.py script on your local machine first.")
                return []
            
            # Initialize driver
            self._init_driver(headless=True)
            
            # Go to Facebook home and load cookies there
            print("Loading Facebook home...")
            self.driver.get("https://www.facebook.com")
            time.sleep(3)
            
            # Load cookies
            print("Loading authentication cookies...")
            with open(COOKIE_FILE, 'r') as f:
                cookies = json.load(f)
            for cookie in cookies:
                try:
                    if 'domain' in cookie and cookie['domain'].startswith('.'):
                        cookie['domain'] = cookie['domain'][1:]
                    self.driver.add_cookie(cookie)
                except:
                    pass
            
            # NOW navigate to coroner page (WITH authentication)
            print(f"Navigating to {FACEBOOK_PAGE_URL} (authenticated)...")
            self.driver.get(FACEBOOK_PAGE_URL)
            
            # Wait much longer for JavaScript to execute and content to load
            print("Waiting for page to fully load...")
            time.sleep(15)
            
            # Check current URL
            current_url = self.driver.current_url
            print(f"Current URL: {current_url}")
            
            if "login" in current_url.lower():
                print("⚠️  Session expired. Need to login again.")
                self.driver.quit()
                COOKIE_FILE.unlink()
                return []
            
            # Scroll to load posts (human-like)
            print("Scrolling to load posts...")
            for i in range(8):
                self._human_like_scroll()
            
            # Wait longer for JavaScript to execute
            print("Waiting for posts to render...")
            time.sleep(10)
            
            # Try to click "See More" buttons to expand posts
            try:
                see_more_buttons = self.driver.find_elements(By.XPATH, "//div[contains(text(), 'See more') or contains(text(), 'See More')]")
                print(f"Found {len(see_more_buttons)} 'See More' buttons")
                for btn in see_more_buttons[:3]:
                    try:
                        btn.click()
                        time.sleep(1)
                    except:
                        pass
            except:
                pass
            
            # Additional wait for content
            time.sleep(5)
            
            # SIMPLER APPROACH: Find ALL content images directly
            # Since this page only posts images, we can find images directly
            print("Finding all content images on page...")
            all_images = self.driver.find_elements(By.TAG_NAME, 'img')
            
            # Filter for actual Facebook content images (scontent CDN)
            content_images = []
            for img in all_images:
                src = img.get_attribute('src')
                if src and 'scontent' in src and 'emoji' not in src.lower() and 'profile' not in src.lower():
                    # Try to filter out profile pictures by size
                    try:
                        size = img.size
                        # Profile pics are usually small (40x40, 160x160), posts are larger
                        if size['width'] > 200 or size['height'] > 200:
                            content_images.append(img)
                    except:
                        content_images.append(img)  # Include if we can't determine size
            
            print(f"Total images on page: {len(all_images)}")
            print(f"Content images (likely posts): {len(content_images)}")
            
            items = []
            for idx, img in enumerate(content_images[:10]):  # Check first 10 images
                try:
                    print(f"\nImage {idx+1}:")
                    
                    image_url = img.get_attribute('src')
                    if not image_url:
                        print(f"  ✗ No src attribute")
                        continue
                    
                    print(f"  📷 Image URL: {image_url[:80]}...")
                    
                    # Extract Facebook post ID from image URL
                    # Facebook image URLs contain the post ID like: ...6/469097400_122182200506092021_...
                    # The long number after the underscore is the post ID
                    import re
                    fb_id_match = re.search(r'_(\d{15,})_', image_url)
                    if fb_id_match:
                        post_id = f"fb_{fb_id_match.group(1)}"
                    else:
                        # Fallback to image hash
                        clean_url = image_url.split('?')[0]
                        post_id = hashlib.sha256(clean_url.encode()).hexdigest()
                    
                    # Try to find the parent post container to get link and text
                    link = FACEBOOK_PAGE_URL
                    text = ""
                    
                    try:
                        # Try to find parent article/post
                        parent = img
                        for _ in range(10):  # Go up max 10 levels
                            parent = parent.find_element(By.XPATH, "..")
                            role = parent.get_attribute('role')
                            if role == 'article':
                                # Found the post container
                                try:
                                    link_elem = parent.find_element(By.XPATH, ".//a[contains(@href, '/posts/') or contains(@href, '/permalink/') or contains(@href, '/photo/')]")
                                    link = link_elem.get_attribute('href')
                                    print(f"  🔗 Link: {link}")
                                except:
                                    pass
                                
                                # Try to get text
                                try:
                                    text = parent.text.strip()
                                except:
                                    pass
                                break
                    except:
                        pass
                    
                    print(f"  🆔 Post ID: {post_id[:60]}...")
                    print(f"  👀 Already seen: {post_id in self.seen_items}")
                    
                    if post_id not in self.seen_items:
                        
                        # Use text if available, otherwise generic title
                        title = text[:100] if text else "Mesa County Coroner - New Post"
                        description = text[:2000] if text else "View the attached image for details."
                        
                        items.append({
                            'id': post_id,
                            'title': title,
                            'link': link,
                            'description': description,
                            'image_url': image_url,
                            'date': datetime.now().strftime('%Y-%m-%d')
                        })
                        print(f"  ✅ New image post added!")
                    else:
                        print(f"  ⏭️  Already seen this image, skipping")
                
                except Exception as e:
                    print(f"  ❌ Error parsing image {idx+1}: {str(e)[:200]}")
                    continue
            
            return items
        
        except Exception as e:
            print(f"Error during scraping: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            if self.driver:
                self.driver.quit()
    
    def _post_to_discord(self, item: Dict, skip_send: bool = False) -> bool:
        """Post to Discord. Set skip_send=True to mark as seen without sending."""
        if skip_send:
            print(f"✓ Marked as seen (not sent): {item['title'][:50]}...")
            return True
            
        try:
            embed = {
                "title": item['title'][:256],
                "url": item['link'],
                "color": COLOR,
                "description": item['description'][:4000],
                "footer": {"text": f"Mesa County Coroner • {item['date']}"},
                "timestamp": datetime.now().isoformat()
            }
            
            if item.get('image_url'):
                embed["image"] = {"url": item['image_url']}
            
            payload = {
                "embeds": [embed],
                "username": "Mesa County Coroner Monitor",
                "avatar_url": "https://www.mesacounty.us/media/1193/logo.png"
            }
            
            response = httpx.post(
                WEBHOOK_URL,
                json=payload,
                timeout=10.0
            )
            
            if response.status_code in [200, 204]:
                print(f"✓ Posted to Discord: {item['title'][:50]}...")
                return True
            else:
                print(f"✗ Discord webhook failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"✗ Error posting to Discord: {e}")
            return False
    
    def run(self):
        """Main run loop"""
        print("\n" + "="*60)
        print(f"Mesa County Coroner Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60 + "\n")
        
        # Scrape posts
        new_posts = self._scrape_posts()
        
        # Post to Discord
        if new_posts:
            print(f"\n📢 Found {len(new_posts)} new post(s)")
            for post in new_posts:
                if self._post_to_discord(post):
                    self._save_seen_item(post['id'])
                time.sleep(2)
        else:
            print("\n✓ No new posts found")
    
    def run_continuous(self, check_interval=300):
        """Run continuously, checking for updates at regular intervals
        
        Args:
            check_interval: Seconds between checks (default: 300 = 5 minutes)
        """
        print("\n" + "="*60)
        print("🚀 MESA COUNTY CORONER MONITOR - CONTINUOUS MODE")
        print("="*60)
        print(f"✓ Monitoring: {FACEBOOK_PAGE_URL}")
        print(f"✓ Check interval: {check_interval} seconds ({check_interval/60:.1f} minutes)")
        print(f"✓ Discord webhook configured")
        print("="*60 + "\n")
        
        check_count = 0
        while True:
            try:
                check_count += 1
                print(f"\n{'='*60}")
                print(f"CHECK #{check_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*60}\n")
                
                # Run a single check
                self.run()
                
                # Wait before next check
                next_check = datetime.now().timestamp() + check_interval
                next_check_time = datetime.fromtimestamp(next_check).strftime('%H:%M:%S')
                print(f"\n⏰ Next check at {next_check_time} (in {check_interval/60:.1f} minutes)")
                print(f"{'='*60}\n")
                
                time.sleep(check_interval)
                
            except KeyboardInterrupt:
                print("\n\n🛑 Monitoring stopped by user")
                break
            except Exception as e:
                print(f"\n❌ Error during check: {e}")
                print(f"⏳ Waiting {check_interval} seconds before retry...")
                time.sleep(check_interval)

def main():
    bot = FacebookStealthBot()
    
    # Check if running in continuous mode
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--continuous':
        # Get interval if provided, default to 5 minutes
        interval = 300  # 5 minutes
        if len(sys.argv) > 2:
            try:
                interval = int(sys.argv[2])
            except:
                print("Invalid interval, using default (300 seconds)")
        bot.run_continuous(check_interval=interval)
    else:
        # Run once
        bot.run()

if __name__ == "__main__":
    main()

