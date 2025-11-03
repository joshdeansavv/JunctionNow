#!/usr/bin/env python3
"""CrimeWatch Article Maker Bot - Discord Bot with OpenAI Integration"""
import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
import httpx
import json
import re
import os
from pathlib import Path
from typing import List, Dict, Set, Optional
from selectolax.parser import HTMLParser
from openai import OpenAI
from dotenv import load_dotenv

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent

# Load environment variables from the script's directory
load_dotenv(SCRIPT_DIR / ".env")

# Configuration (matching the actual .env variable names)
DISCORD_TOKEN = os.getenv("discord_bot_token")
OPENAI_API_KEY = os.getenv("OPENAI_TOKEN")
CHANNEL_ID = int(os.getenv("channel_id", "0"))  # Channel to post articles
CRIMEWATCH_URL = "https://crimewatch.net/us/co/mesa"
SEEN_FILE = SCRIPT_DIR / "seen_items.json"

COLOR = 0x3F51BF  # Blue color (4144959 in decimal)
MAX_ITEMS = 15
CHECK_INTERVAL = 600  # Check every 10 minutes

# Initialize OpenAI client (will be set after env is loaded)
openai_client = None

# Bot setup with intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


class ArticleView(View):
    """View with Skip and Make Article buttons"""
    def __init__(self, article_data: Dict, bot_instance):
        super().__init__(timeout=None)  # No timeout
        self.article_data = article_data
        self.bot_instance = bot_instance
        self.processed = False
    
    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, custom_id="skip")
    async def skip_button(self, interaction: discord.Interaction, button: Button):
        """Skip this article"""
        if self.processed:
            await interaction.response.send_message("This article has already been processed.", ephemeral=True)
            return
        
        self.processed = True
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        # Edit the message to disable buttons
        await interaction.response.edit_message(view=self)
        
        # Send confirmation
        await interaction.followup.send(f"✓ Skipped article: **{self.article_data['title']}**", ephemeral=True)
    
    @discord.ui.button(label="Make Article", style=discord.ButtonStyle.primary, custom_id="make_article")
    async def make_article_button(self, interaction: discord.Interaction, button: Button):
        """Generate article using OpenAI"""
        if self.processed:
            await interaction.response.send_message("This article has already been processed.", ephemeral=True)
            return
        
        self.processed = True
        
        # IMPORTANT: Defer the interaction immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        # Edit the original message to disable buttons
        await interaction.message.edit(view=self)
        
        # Send initial status message (we'll delete it later)
        status_msg = await interaction.followup.send("⏳ Generating article with OpenAI...", ephemeral=True, wait=True)
        
        # Generate article
        try:
            # Fetch full article content (no limits)
            article_content = await self.bot_instance.fetch_article_content(self.article_data['link'])
            print(f"\n{'='*60}")
            print(f"Article URL: {self.article_data['link']}")
            print(f"Article Content Length: {len(article_content)} chars")
            print(f"Article Content Preview: {article_content[:500]}...")
            print(f"{'='*60}\n")
            
            # Check if article content is valid
            if not article_content or article_content == "Unable to fetch article content" or article_content == "Unable to extract article content":
                await status_msg.delete()
                await interaction.followup.send(f"❌ Could not fetch article content from the website.", ephemeral=True)
                print("ERROR: Failed to fetch article content")
                return
            
            if len(article_content) < 50:
                await status_msg.delete()
                await interaction.followup.send(f"❌ Article content is too short ({len(article_content)} chars).", ephemeral=True)
                print(f"ERROR: Article content too short: {article_content}")
                return
            
            # Create prompt - keep it simple, no em dashes
            prompt = f"Summarize the following press release into a news article with a title and article. Keep the title short and professional. If a bulleted list is included, keep its structure for a clean looking article. Do NOT use em dashes (—) or special characters. Use simple hyphens (-) only.\n\nPress Release:\n{article_content}"
            
            print(f"Calling OpenAI API with {len(prompt)} char prompt...")
            
            # Call OpenAI API
            response = openai_client.chat.completions.create(
                model="gpt-5-nano",
                messages=[
                    {"role": "system", "content": "You are a professional news article writer. Generate concise, professional news articles from press releases."},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1500
            )
            
            generated_text = response.choices[0].message.content.strip() if response.choices[0].message.content else ""
            
            # Debug logging
            print(f"\n{'='*60}")
            print(f"OpenAI Response Length: {len(generated_text)} chars")
            print(f"OpenAI Response:\n{generated_text}")
            print(f"{'='*60}\n")
            
            # Validate response
            if not generated_text or len(generated_text) < 10:
                await status_msg.delete()
                await interaction.followup.send(f"❌ OpenAI returned an empty or very short response ({len(generated_text)} chars). Check terminal logs.", ephemeral=True)
                print(f"ERROR: OpenAI response too short or empty")
                return
            
            # Use OpenAI response directly - no parsing
            # Just wrap the entire response in backticks
            embed = discord.Embed(
                description=f"```{generated_text}```",
                color=COLOR
            )
            
            # Determine username from article source
            username = self.determine_username(self.article_data)
            
            # Send the article (using webhook-style format via embed)
            # Mention the user who requested it
            await interaction.channel.send(
                content=f"**{username}** - Requested by {interaction.user.mention}",
                embed=embed
            )
            
            # Delete the "generating" status message
            await status_msg.delete()
        
        except Exception as e:
            # Delete the "generating" status message and show error
            try:
                await status_msg.delete()
            except:
                pass
            await interaction.followup.send(f"❌ Error generating article: {str(e)}", ephemeral=True)
            print(f"Error generating article: {e}")
    
    
    def determine_username(self, article_data: Dict) -> str:
        """Determine username based on article source"""
        title = article_data.get('title', '').lower()
        
        if 'sheriff' in title or 'mcso' in title:
            return "Mesa County Sheriff"
        elif 'police' in title or 'gjpd' in title:
            return "Grand Junction Police"
        elif 'fire' in title:
            return "Fire Department"
        else:
            return "CrimeWatch Mesa County"


class CrimeWatchBot:
    """Scraper for CrimeWatch articles"""
    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            },
            timeout=30.0,
            follow_redirects=True
        )
        self.seen_items = self._load_seen_items()
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    def _load_seen_items(self) -> Set[str]:
        """Load seen items from JSON file"""
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
        """Save seen item to JSON file"""
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
        except Exception as e:
            print(f"Error saving seen item: {e}")
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        return text
    
    async def scrape_news_feed(self) -> List[Dict]:
        """Scrape news feed from CrimeWatch Mesa County"""
        try:
            response = await self.client.get(CRIMEWATCH_URL)
            if response.status_code != 200:
                print(f"Failed to fetch page: {response.status_code}")
                return []
            
            tree = HTMLParser(response.text)
            items = []
            
            # Find all news items
            news_items = tree.css('div.news-single-card')
            
            if not news_items:
                print("No news items found")
                return []
            
            # Parse each news item
            for item in news_items[:MAX_ITEMS]:
                try:
                    # Extract title
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
                    
                    # Extract description
                    desc_elems = item.css('div.single-news-subtitle')
                    description = ""
                    if desc_elems:
                        for desc_elem in desc_elems:
                            text = self._clean_text(desc_elem.text())
                            if len(text) > 50:
                                description = text
                                break
                        
                        if len(description) > 2000:
                            description = description[:1997] + "..."
                    
                    # Extract image
                    image_url = None
                    img_elem = item.css_first('div.img-wrapper img[src]')
                    if img_elem and 'src' in img_elem.attributes:
                        image_url = img_elem.attributes['src']
                        if image_url.startswith('/'):
                            image_url = f"https://crimewatch.net{image_url}"
                        elif not image_url.startswith('http'):
                            image_url = f"https://crimewatch.net/{image_url}"
                    
                    # Extract date
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
    
    async def fetch_article_content(self, url: str) -> str:
        """Fetch full article content from URL"""
        try:
            response = await self.client.get(url)
            if response.status_code != 200:
                return "Unable to fetch article content"
            
            tree = HTMLParser(response.text)
            
            # Try to find the main content area
            content_elem = tree.css_first('div.article-content, div.news-content, article, div.content')
            if content_elem:
                text = self._clean_text(content_elem.text())
                return text  # Return FULL content, no limits
            
            # Fallback: get all paragraphs
            paragraphs = tree.css('p')
            if paragraphs:
                text = ' '.join([self._clean_text(p.text()) for p in paragraphs])
                return text  # Return FULL content, no limits
            
            return "Unable to extract article content"
        
        except Exception as e:
            print(f"Error fetching article content: {e}")
            return "Unable to fetch article content"
    
    def mark_as_seen(self, item_id: str):
        """Mark an item as seen"""
        self._save_seen_item(item_id)


# Global scraper instance
scraper = CrimeWatchBot()


@bot.event
async def on_ready():
    """Called when bot is ready"""
    global openai_client
    
    # Initialize OpenAI client
    if openai_client is None and OPENAI_API_KEY:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        print("✓ OpenAI client initialized")
    
    print(f"✓ Bot logged in as {bot.user}")
    print(f"✓ Bot ID: {bot.user.id}")
    
    # Start the background task
    if not check_for_articles.is_running():
        check_for_articles.start()
        print("✓ Article checker task started")


@tasks.loop(seconds=CHECK_INTERVAL)
async def check_for_articles():
    """Background task to check for new articles"""
    try:
        if CHANNEL_ID == 0:
            print("❌ CHANNEL_ID not set in .env")
            return
        
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            print(f"❌ Channel {CHANNEL_ID} not found")
            return
        
        print("🔍 Checking for new articles...")
        
        # Scrape articles
        articles = await scraper.scrape_news_feed()
        
        if not articles:
            print("No new articles found")
            return
        
        # Post each article with buttons
        for article in articles:
            try:
                # Create embed
                embed = discord.Embed(
                    title=article['title'],
                    url=article['link'],
                    color=COLOR
                )
                
                if article.get('description'):
                    embed.description = article['description']
                
                if article.get('image_url'):
                    embed.set_image(url=article['image_url'])
                
                if article.get('date'):
                    embed.set_footer(text=article['date'])
                
                # Create view with buttons
                view = ArticleView(article, scraper)
                
                # Post to channel
                await channel.send(embed=embed, view=view)
                
                # Mark as seen
                scraper.mark_as_seen(article['id'])
                
                print(f"✓ Posted: {article['title']}")
            
            except Exception as e:
                print(f"❌ Error posting article: {e}")
        
        print(f"✓ Posted {len(articles)} new articles")
    
    except Exception as e:
        print(f"❌ Error in check_for_articles: {e}")


@check_for_articles.before_loop
async def before_check_for_articles():
    """Wait until bot is ready before starting task"""
    await bot.wait_until_ready()


@bot.command(name="check")
@commands.has_permissions(administrator=True)
async def manual_check(ctx):
    """Manually trigger article check (Admin only)"""
    await ctx.send("🔍 Checking for new articles...")
    await check_for_articles()
    await ctx.send("✓ Check complete!")


@bot.command(name="status")
async def status(ctx):
    """Check bot status"""
    seen_count = len(scraper.seen_items)
    await ctx.send(f"✓ Bot is online!\n📊 Tracked articles: {seen_count}")


async def shutdown():
    """Gracefully shutdown the bot"""
    print("\n⏹ Shutting down gracefully...")
    
    # Close scraper
    try:
        await scraper.close()
        print("✓ Scraper closed")
    except Exception as e:
        print(f"⚠ Error closing scraper: {e}")
    
    # Close bot connection
    try:
        if not bot.is_closed():
            await bot.close()
            print("✓ Bot disconnected")
    except Exception as e:
        print(f"⚠ Error closing bot: {e}")
    
    print("✓ Shutdown complete")


async def main():
    """Main function to run the bot"""
    try:
        print("🔧 Checking environment variables...")
        print(f"   Discord Token: {'✓' if DISCORD_TOKEN else '✗'}")
        print(f"   OpenAI Key: {'✓' if OPENAI_API_KEY else '✗'}")
        print(f"   Channel ID: {CHANNEL_ID}")
        
        if not DISCORD_TOKEN:
            print("❌ discord_bot_token not found in .env")
            return
        
        if not OPENAI_API_KEY:
            print("❌ OPENAI_TOKEN not found in .env")
            return
        
        print("🚀 Starting bot...")
        await bot.start(DISCORD_TOKEN)
    
    except KeyboardInterrupt:
        pass  # Handle gracefully
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        await shutdown()


if __name__ == "__main__":
    import asyncio
    import signal
    
    # Handle Ctrl+C and other signals gracefully
    def signal_handler(sig, frame):
        print("\n⏹ Received shutdown signal...")
        raise KeyboardInterrupt
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("✓ Bot stopped")

