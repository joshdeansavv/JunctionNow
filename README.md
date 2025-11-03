# JunctionNow

A collection of Python bots for monitoring and aggregating local news, weather, and public safety information for Western Colorado.

## Projects

### 🚗 CDOT Traffic Bot
Monitors Colorado Department of Transportation traffic cameras and road conditions.
- **File**: `CDOT/main.py`
- **Features**: Real-time traffic camera images, road conditions, weather alerts

### 👮 Crime Watch Bot
Scrapes and posts crime alerts from CrimeWatch Mesa County.
- **File**: `crime_watch/main.py`
- **Source**: https://crimewatch.net/us/co/mesa

### 📰 Crime Watch Article Maker
Discord bot that generates AI-powered news articles from crime reports using OpenAI.
- **File**: `crime_watch_article_maker/main.py`
- **Features**: Interactive buttons, OpenAI integration, automated article generation

### 🏛️ County News Bot
Aggregates news from Mesa County and City of Grand Junction.
- **File**: `county_news/main.py`
- **Sources**: Mesa County official news, City of Grand Junction RSS

### 📺 Local News Source Feed
Monitors local Western Colorado news outlets with location-based filtering.
- **File**: `local_news_source_feed/main.py`
- **Sources**: KJCT8, Western Slope Now, Daily Sentinel

### ⚰️ Coroner Watch Bot
Monitors Mesa County Coroner's Office Facebook page for updates.
- **File**: `coroner_watch/main_selenium_stealth.py`
- **Technology**: Selenium with stealth mode for Facebook scraping

### 🌤️ NOAA Weather Bot
Fetches and displays weather data from NOAA/National Weather Service.
- **File**: `noaa_weather/main.py`
- **Features**: Current conditions, forecasts, radar imagery, weather alerts

### 🚨 FDA Recalls Bot
Monitors FDA recalls, market withdrawals, and safety alerts.
- **File**: `recall_rss_bot/main.py`
- **Source**: https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts

## Setup

### Prerequisites
- Python 3.8+
- Discord webhooks (for posting notifications)
- Environment variables for sensitive data

### Installation

1. Clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/JunctionNow.git
cd JunctionNow
```

2. Install dependencies for each bot:
```bash
cd bot_folder
pip install -r requirements.txt  # (create as needed)
```

3. Configure environment variables:
Create a `.env` file in each bot folder with required credentials:
```env
# Example for CDOT bot
API_KEY=your_api_key
API_SECRET=your_api_secret

# Example for Discord bots
DISCORD_WEBHOOK_URL=your_webhook_url

# Example for OpenAI bots
OPENAI_TOKEN=your_openai_token
discord_bot_token=your_discord_bot_token
channel_id=your_channel_id
```

### Configuration

Each bot has configuration constants at the top of the file:
- `WEBHOOK_URL` or `DISCORD_WEBHOOKS`: Your Discord webhook URLs
- `*_URL`: RSS feeds and API endpoints (already configured)
- `SEEN_FILE`: Path to tracking file for posted items

## Usage

Run any bot individually:
```bash
python bot_folder/main.py
```

Some bots support additional arguments:
```bash
# Weather bot
python noaa_weather/main.py --discord --verbose

# CDOT bot
python CDOT/main.py --once

# Coroner watch bot
python coroner_watch/main_selenium_stealth.py --continuous 300
```

## Features

- **RSS Feed Parsing**: Automated monitoring of news feeds
- **Web Scraping**: Advanced scraping with stealth techniques
- **Discord Integration**: Webhook and bot support for notifications
- **OpenAI Integration**: AI-powered article generation
- **Image Handling**: Automatic image extraction and posting
- **Duplicate Detection**: Tracks seen items to avoid reposts
- **Scheduling**: Built-in scheduling for automated checks

## Technologies

- **httpx**: Async HTTP client
- **feedparser**: RSS/Atom feed parsing
- **selectolax**: Fast HTML parsing
- **selenium + undetected-chromedriver**: Stealth web scraping
- **discord.py**: Discord bot framework
- **openai**: AI article generation
- **schedule**: Task scheduling

## License

MIT License - Feel free to use and modify for your own projects.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

These bots are designed for personal use and educational purposes. Always respect website terms of service and rate limits when scraping data.

