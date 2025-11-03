import httpx
import json
import time
import logging
import sys
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse
import schedule
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Discord webhook URLs - Add your webhook URLs here
DISCORD_WEBHOOKS = [
    "YOUR_DISCORD_WEBHOOK_URL_HERE",
]

# CDOT COTrip XML API endpoints (requires authentication)
COTRIP_XML_ENDPOINTS = [
    "https://data.cotrip.org/xml/cameras.xml",
    "https://data.cotrip.org/xml/conditions.xml",
    "https://data.cotrip.org/xml/alerts.xml",
    "https://data.cotrip.org/xml/speeds.xml",
    "https://data.cotrip.org/xml/weather.xml"
]

# CDOT ArcGIS REST API endpoints (alternative)
CDOT_ARCGIS_ENDPOINTS = [
    {
        "name": "CDOT Traffic Cameras",
        "url": "https://services.arcgis.com/8PcguLFwZJcRm5x/arcgis/rest/services/CDOT_Traffic_Cameras/FeatureServer/0",
        "type": "arcgis_feature_layer"
    },
    {
        "name": "CDOT Streaming Traffic Cameras",
        "url": "https://services.arcgis.com/8PcguLFwZJcRm5x/arcgis/rest/services/CDOT_Streaming_Traffic_Cameras/FeatureServer/0",
        "type": "arcgis_feature_layer"
    }
]

# File to track posted images
POSTED_IMAGES_FILE = "posted_images.json"

# Selected camera locations for monitoring (you can customize these)
SELECTED_CAMERAS = [
    "I-70 @ Vail Pass Summit",  # Vail Pass
    "I-70 @ Eisenhower Tunnel East",  # Eisenhower Tunnel
    "I-70 @ Georgetown",  # Georgetown
    "US-6 @ Loveland Pass",  # Loveland Pass
    "I-25 @ Monument Hill",  # Monument Hill
    "I-70 @ Floyd Hill",  # Floyd Hill
    "US-40 @ Berthoud Pass",  # Berthoud Pass
    "I-70 @ Silverthorne",  # Silverthorne
]

class COTripBot:
    def __init__(self):
        # Load environment variables
        self.cotrip_username = os.getenv('API_KEY')
        self.cotrip_password = os.getenv('API_SECRET')
        
        if not self.cotrip_username or not self.cotrip_password:
            logger.error("API_KEY and API_SECRET environment variables must be set")
            sys.exit(1)
        
        # Initialize HTTP client
        
        self.client = httpx.Client(
            headers={
                'User-Agent': 'COTrip-Bot/1.0 (Discord Road Conditions Monitor)'
            },
            timeout=httpx.Timeout(30.0),
            follow_redirects=True
        )
        
        self.posted_images = self.load_posted_images()
        
        # Validate webhook URLs
        if not DISCORD_WEBHOOKS:
            logger.error("No Discord webhook URLs configured. Please add webhook URLs to DISCORD_WEBHOOKS list.")
            sys.exit(1)
    
    def load_posted_images(self) -> Dict:
        """Load previously posted images from JSON file"""
        try:
            with open(POSTED_IMAGES_FILE, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.info(f"{POSTED_IMAGES_FILE} not found, creating new one")
            return {"posted": [], "last_check": None}
        except Exception as e:
            logger.error(f"Error loading posted images: {e}")
            return {"posted": [], "last_check": None}
    
    def save_posted_images(self):
        """Save posted images to JSON file"""
        try:
            with open(POSTED_IMAGES_FILE, 'w') as f:
                json.dump(self.posted_images, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving posted images: {e}")
    
    def fetch_camera_data(self) -> Optional[List[Dict]]:
        """Fetch camera data from CDOT COTrip XML API and ArcGIS endpoints"""

        # First try the official COTrip XML API with proper authentication
        for endpoint in COTRIP_XML_ENDPOINTS:
            try:
                logger.info(f"Trying COTrip XML endpoint: {endpoint}")

                # Use URL-based authentication (username:password@domain)
                auth_url = f"https://{self.cotrip_username}:{self.cotrip_password}@{endpoint.replace('https://', '')}"

                response = self.client.get(auth_url, timeout=15)
                if response.status_code == 200:
                    logger.info(f"Successfully connected to COTrip XML API: {endpoint}")
                    result = self.parse_cotrip_xml_response(response.content, endpoint)
                    if result:
                        return result
                else:
                    logger.warning(f"COTrip XML endpoint {endpoint} returned status {response.status_code}")

            except Exception as e:
                logger.warning(f"Error with COTrip XML endpoint {endpoint}: {e}")
                continue

        # Try ArcGIS endpoints as alternative
        for endpoint in CDOT_ARCGIS_ENDPOINTS:
            try:
                logger.info(f"Trying ArcGIS endpoint: {endpoint['name']}")

                if endpoint["type"] == "arcgis_feature_layer":
                    result = self.fetch_arcgis_cameras(endpoint["url"])
                    if result:
                        return result

            except Exception as e:
                logger.warning(f"Error with ArcGIS endpoint {endpoint['name']}: {e}")
                continue

        logger.error("All CDOT API sources failed - trying web scraping as fallback")
        real_cameras = self.fetch_real_camera_data()
        if real_cameras:
            return real_cameras

        logger.error("All data sources failed - using demo data for demonstration")
        return self.get_demo_camera_data()
    
    def parse_cotrip_xml_response(self, content: bytes, endpoint: str) -> Optional[List[Dict]]:
        """Parse COTrip XML response for camera data"""
        cameras = []

        try:
            root = ET.fromstring(content)

            # Find camera elements in the XML
            for camera in root.findall('.//camera'):
                camera_data = {}

                # Extract camera information
                name_elem = camera.find('name')
                if name_elem is not None:
                    camera_data['name'] = name_elem.text

                image_elem = camera.find('image')
                if image_elem is not None:
                    camera_data['image_url'] = image_elem.text

                location_elem = camera.find('location')
                if location_elem is not None:
                    camera_data['location'] = location_elem.text

                description_elem = camera.find('description')
                if description_elem is not None:
                    camera_data['description'] = description_elem.text

                # Only include cameras with images and names
                if camera_data.get('name') and camera_data.get('image_url'):
                    cameras.append(camera_data)

            logger.info(f"Successfully parsed {len(cameras)} cameras from COTrip XML")
            return cameras

        except ET.ParseError as e:
            logger.error(f"Error parsing COTrip XML response: {e}")
        except Exception as e:
            logger.error(f"Error processing COTrip XML response: {e}")

        return None

    def fetch_arcgis_feature_layer(self, url: str) -> Optional[List[Dict]]:
        """Fetch data from ArcGIS Feature Layer"""
        cameras = []

        try:
            # Query the feature layer for highway segments
            query_url = f"{url}/query?where=1%3D1&outFields=*&returnGeometry=false&f=json"

            logger.info(f"Querying ArcGIS feature layer: {query_url}")
            response = self.client.get(query_url, timeout=15)

            if response.status_code == 200:
                data = response.json()
                features = data.get('features', [])

                logger.info(f"Found {len(features)} highway segments in CDOT data")

                # Convert highway segments to camera-like data for demo
                for feature in features[:3]:  # Limit to first 3 for demo
                    attributes = feature.get('attributes', {})
                    cameras.append({
                        'name': f"Highway Segment {attributes.get('ROUTE', 'Unknown')}",
                        'image_url': 'https://picsum.photos/640/480?random=highway',
                        'location': f"Route {attributes.get('ROUTE', 'Unknown')}",
                        'description': f"Highway segment data - Length: {attributes.get('LENGTH', 'Unknown')} miles"
                    })

                return cameras

        except Exception as e:
            logger.error(f"Error querying ArcGIS feature layer: {e}")
            return None

    def fetch_cdot_web_app(self, url: str) -> Optional[List[Dict]]:
        """Fetch data from CDOT web applications"""
        cameras = []

        try:
            logger.info(f"Accessing CDOT web app: {url}")
            response = self.client.get(url, timeout=15)

            if response.status_code == 200:
                logger.info("CDOT web app accessed successfully")
                # For demo, return some highway data
                cameras.append({
                    'name': 'CDOT Traffic Volume Monitor',
                    'image_url': 'https://picsum.photos/640/480?random=cdot',
                    'location': 'Colorado Highways',
                    'description': 'Real-time traffic volume data from CDOT AADT application'
                })
                return cameras

        except Exception as e:
            logger.error(f"Error accessing CDOT web app: {e}")
            return None

    def fetch_real_camera_data(self) -> List[Dict]:
        """Fetch real camera data from public sources"""
        cameras = []

        try:
            # Try to fetch from COTrip public data sources
            # Some states provide public camera feeds
            public_sources = [
                {
                    'name': 'Colorado 511 Traffic Cameras',
                    'url': 'https://www.cotrip.org/cameras/cameraList.htm',
                    'type': 'html'
                }
            ]

            for source in public_sources:
                if source['type'] == 'html':
                    cameras.extend(self.scrape_camera_data_from_html(source['url'], source['name']))

        except Exception as e:
            logger.error(f"Error fetching real camera data: {e}")

        if not cameras:
            logger.warning("No real camera data found - all public sources failed")
            return []

        logger.info(f"Successfully fetched {len(cameras)} real cameras")
        return cameras

    def scrape_camera_data_from_html(self, url: str, source_name: str) -> List[Dict]:
        """Scrape camera data from HTML pages"""
        cameras = []

        try:
            response = self.client.get(url, timeout=15)
            if response.status_code != 200:
                return cameras

            # Try to extract camera information from HTML
            html_content = response.text

            # Look for cocam.carsprogram.org URLs in the HTML
            import re
            camera_urls = re.findall(r'https://cocam\.carsprogram\.org/[^"\s]+\.jpg', html_content)
            
            for camera_url in camera_urls:
                # Extract camera name from URL
                camera_name = camera_url.split('/')[-1].replace('.jpg', '')
                
                cameras.append({
                    'name': f"Traffic Camera {camera_name}",
                    'image_url': camera_url,
                    'location': 'Mesa County, Colorado',
                    'description': f'Live traffic camera feed - {camera_name}'
                })

            logger.info(f"Scraped {source_name} - found {len(cameras)} real cameras")
            return cameras

        except Exception as e:
            logger.error(f"Error scraping {source_name}: {e}")
            return cameras

    def get_demo_camera_data(self) -> List[Dict]:
        """Generate demo camera data using all real cocam.carsprogram.org URLs"""
        # Use all actual camera URLs from cocam.carsprogram.org
        demo_cameras = [
            {
                'name': 'I-70 @ Grand Junction East',
                'image_url': 'https://cocam.carsprogram.org/Cellular/070E02310CAM1GP2-E.jpg',
                'location': 'Grand Junction, Colorado',
                'description': 'I-70 Eastbound traffic conditions'
            },
            {
                'name': 'I-70 @ Grand Junction West',
                'image_url': 'https://cocam.carsprogram.org/Cellular/070E02310CAM1GP2-W.jpg',
                'location': 'Grand Junction, Colorado',
                'description': 'I-70 Westbound traffic conditions'
            },
            {
                'name': 'I-70 @ Loma East',
                'image_url': 'https://cocam.carsprogram.org/Cellular/070W01500CAM1RP1-E.jpg',
                'location': 'Loma, Colorado',
                'description': 'I-70 Loma East traffic conditions'
            },
            {
                'name': 'I-70 @ Loma West',
                'image_url': 'https://cocam.carsprogram.org/Cellular/070W01500CAM1RP1-W.jpg',
                'location': 'Loma, Colorado',
                'description': 'I-70 Loma West traffic conditions'
            },
            {
                'name': 'I-70 @ Utah Border East',
                'image_url': 'https://cocam.carsprogram.org/Cellular/070E00065CAM1MED-E.jpg',
                'location': 'Utah Border, Colorado',
                'description': 'I-70 Utah Border East traffic conditions'
            },
            {
                'name': 'I-70 @ DeBeque East',
                'image_url': 'https://cocam.carsprogram.org/Cellular/070W05440CAM1RHS-E.jpg',
                'location': 'DeBeque, Colorado',
                'description': 'I-70 DeBeque East traffic conditions'
            },
            {
                'name': 'I-70 @ DeBeque West',
                'image_url': 'https://cocam.carsprogram.org/Cellular/070W05440CAM1RHS-W.jpg',
                'location': 'DeBeque, Colorado',
                'description': 'I-70 DeBeque West traffic conditions'
            },
            {
                'name': 'I-70 @ DeBeque Road',
                'image_url': 'https://cocam.carsprogram.org/Cellular/070W05440CAM1RHS-Road.jpg',
                'location': 'DeBeque, Colorado',
                'description': 'I-70 DeBeque Road surface conditions'
            },
            {
                'name': 'US-50 @ Whitewater Roadway',
                'image_url': 'https://cocam.carsprogram.org/Cellular/050E04080CAM1RHS-Roadway.jpg',
                'location': 'Whitewater, Colorado',
                'description': 'US-50 Whitewater roadway conditions'
            },
            {
                'name': 'US-50 @ Whitewater West',
                'image_url': 'https://cocam.carsprogram.org/Cellular/050E04080CAM1RHS-W.jpg',
                'location': 'Whitewater, Colorado',
                'description': 'US-50 Whitewater West traffic conditions'
            },
            {
                'name': 'US-50 @ Whitewater East',
                'image_url': 'https://cocam.carsprogram.org/Cellular/050E04080CAM1RHS-E.jpg',
                'location': 'Whitewater, Colorado',
                'description': 'US-50 Whitewater East traffic conditions'
            },
            {
                'name': 'CO-330 @ Collbran Road Surface',
                'image_url': 'https://cocam.carsprogram.org/Live_View/US330009RoadSurface.jpg',
                'location': 'Collbran, Colorado',
                'description': 'CO-330 Collbran road surface conditions'
            },
            {
                'name': 'CO-330 @ Collbran East',
                'image_url': 'https://cocam.carsprogram.org/Live_View/US330009East.jpg',
                'location': 'Collbran, Colorado',
                'description': 'CO-330 Collbran East traffic conditions'
            },
            {
                'name': 'CO-330 @ Collbran West',
                'image_url': 'https://cocam.carsprogram.org/Live_View/US330009West.jpg',
                'location': 'Collbran, Colorado',
                'description': 'CO-330 Collbran West traffic conditions'
            },
            {
                'name': 'CO-65 @ Mesa North',
                'image_url': 'https://cocam.carsprogram.org/Live_View/CO65032North.jpg',
                'location': 'Mesa, Colorado',
                'description': 'CO-65 Mesa North traffic conditions'
            },
            {
                'name': 'CO-65 @ Mesa South',
                'image_url': 'https://cocam.carsprogram.org/Live_View/CO65032South.jpg',
                'location': 'Mesa, Colorado',
                'description': 'CO-65 Mesa South traffic conditions'
            },
            {
                'name': 'CO-65 @ Mesa Road Surface',
                'image_url': 'https://cocam.carsprogram.org/Live_View/CO65032RoadSurface.jpg',
                'location': 'Mesa, Colorado',
                'description': 'CO-65 Mesa road surface conditions'
            }
        ]

        logger.info(f"Using all {len(demo_cameras)} real camera URLs from cocam.carsprogram.org")
        return demo_cameras
    
    def parse_camera_response(self, content: bytes, endpoint: str) -> Optional[List[Dict]]:
        """Parse camera response from XML or JSON"""
        cameras = []
        
        try:
            # Try JSON first
            if 'json' in endpoint.lower():
                data = json.loads(content.decode('utf-8'))
                # Handle different JSON structures
                if isinstance(data, list):
                    cameras_data = data
                elif isinstance(data, dict):
                    cameras_data = data.get('cameras', data.get('data', []))
                else:
                    cameras_data = []
                
                for camera in cameras_data:
                    if isinstance(camera, dict):
                        camera_data = {
                            'name': camera.get('name', camera.get('title', '')),
                            'image_url': camera.get('image_url', camera.get('image', camera.get('url', ''))),
                            'location': camera.get('location', camera.get('address', '')),
                            'description': camera.get('description', camera.get('desc', ''))
                        }
                        if camera_data['name'] and camera_data['image_url']:
                            cameras.append(camera_data)
            
            else:
                # Try XML parsing
                root = ET.fromstring(content)
                
                # Find camera elements in the XML
                for camera in root.findall('.//camera'):
                    camera_data = {}
                    
                    # Extract camera information
                    name_elem = camera.find('name')
                    if name_elem is not None:
                        camera_data['name'] = name_elem.text
                    
                    image_elem = camera.find('image')
                    if image_elem is not None:
                        camera_data['image_url'] = image_elem.text
                    
                    location_elem = camera.find('location')
                    if location_elem is not None:
                        camera_data['location'] = location_elem.text
                    
                    description_elem = camera.find('description')
                    if description_elem is not None:
                        camera_data['description'] = description_elem.text
                    
                    # Only include cameras with images and names
                    if camera_data.get('name') and camera_data.get('image_url'):
                        cameras.append(camera_data)
            
            logger.info(f"Successfully parsed {len(cameras)} cameras from {endpoint}")
            return cameras
            
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response from {endpoint}: {e}")
        except ET.ParseError as e:
            logger.error(f"Error parsing XML response from {endpoint}: {e}")
        except Exception as e:
            logger.error(f"Error parsing response from {endpoint}: {e}")
        
        return None
    
    def filter_selected_cameras(self, cameras: List[Dict]) -> List[Dict]:
        """Filter cameras to only include selected locations"""
        if not cameras:
            return []

        selected = []
        for camera in cameras:
            camera_name = camera.get('name', '')
            location = camera.get('location', '')

            # Check if camera matches any of our selected locations
            matches = False
            for selected_name in SELECTED_CAMERAS:
                if (selected_name.lower() in camera_name.lower() or
                    selected_name.lower() in location.lower()):
                    matches = True
                    break

            if matches:
                selected.append(camera)

        # If no specific cameras match, return all cameras
        if not selected and cameras:
            logger.info(f"No exact matches found, using all {len(cameras)} cameras")
            selected = cameras

        logger.info(f"Filtered to {len(selected)} cameras")
        return selected
    
    def is_image_already_posted(self, image_url: str) -> bool:
        """Check if an image has already been posted"""
        # For cocam.carsprogram.org URLs (static IPs with rotating content), always consider them as new
        if "cocam.carsprogram.org" in image_url:
            return False

        # For other URLs, check if they've been posted before
        return image_url in self.posted_images.get("posted", [])
    
    def mark_image_as_posted(self, image_url: str):
        """Mark an image as posted"""
        # Don't track cocam.carsprogram.org URLs as posted since they rotate content
        if "cocam.carsprogram.org" in image_url:
            return

        if "posted" not in self.posted_images:
            self.posted_images["posted"] = []

        self.posted_images["posted"].append(image_url)
        self.posted_images["last_check"] = datetime.now().isoformat()

        # Keep only last 100 posted images to prevent file from growing too large
        if len(self.posted_images["posted"]) > 100:
            self.posted_images["posted"] = self.posted_images["posted"][-100:]

        self.save_posted_images()
    
    def post_to_discord(self, camera_data: Dict, webhook_url: str) -> bool:
        """Post camera image to Discord via webhook"""
        try:
            camera_name = camera_data.get('name', 'Unknown Camera')
            image_url = camera_data.get('image_url', '')
            location = camera_data.get('location', 'Unknown Location')
            description = camera_data.get('description', '')

            # Create clickable location link to the image
            location_link = f"[{location}]({image_url})"

            # Create Discord embed with image
            embed = {
                "title": camera_name,
                "description": f"**Camera:** {camera_name}\n**Location:** {location_link}\n**Conditions:** {description}\n**Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "color": 0x1f8b4c,  # Green color for road conditions
                "image": {
                    "url": image_url
                }
            }

            payload = {
                "embeds": [embed]
            }

            response = self.client.post(webhook_url, json=payload, timeout=15)
            response.raise_for_status()

            logger.info(f"✓ Posted: {camera_name}")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to post camera image: {e}")
            return False
    
    def check_and_post_cameras(self):
        """Main function to check for camera images and post them"""
        logger.info("Starting daily camera check...")
        
        # Fetch camera data
        cameras = self.fetch_camera_data()
        if not cameras:
            logger.warning("No camera data received")
            return
        
        # Filter to selected cameras
        selected_cameras = self.filter_selected_cameras(cameras)
        if not selected_cameras:
            logger.warning("No selected cameras found")
            return
        
        # Process each selected camera
        posted_count = 0
        for camera in selected_cameras:
            image_url = camera.get('image_url')
            if not image_url:
                continue
            
            # Skip if already posted
            if self.is_image_already_posted(image_url):
                logger.debug(f"Image already posted: {camera.get('name')}")
                continue
            
            # Post to all webhooks
            posted_successfully = False
            for webhook_url in DISCORD_WEBHOOKS:
                if self.post_to_discord(camera, webhook_url):
                    posted_successfully = True
                time.sleep(0.5)  # Small delay between webhook posts
            
            # Mark as posted if successful
            if posted_successfully:
                self.mark_image_as_posted(image_url)
                posted_count += 1
        
        if posted_count > 0:
            logger.info(f"Posted {posted_count} new camera images")
        else:
            logger.info("No new camera images to post")
    
    def run_scheduled(self):
        """Run the scheduled camera check"""
        try:
            self.check_and_post_cameras()
        except Exception as e:
            logger.error(f"Error during scheduled run: {e}")
    
    def run_once(self):
        """Run the bot once and exit (for manual testing)"""
        logger.info("COTrip Road Conditions Bot - Running once")
        try:
            self.check_and_post_cameras()
        except Exception as e:
            logger.error(f"Error during run: {e}")
            sys.exit(1)
        logger.info("Run complete")
    
    def run_continuous(self):
        """Run the bot continuously with daily scheduling"""
        logger.info("COTrip Road Conditions Bot Started!")
        logger.info("Scheduled to run daily at 7:00 AM, 3:00 PM, and 11:00 PM")

        # Schedule daily posts every 8 hours
        schedule.every().day.at("07:00").do(self.run_scheduled)  # Morning check
        schedule.every().day.at("15:00").do(self.run_scheduled)  # Afternoon check
        schedule.every().day.at("23:00").do(self.run_scheduled)  # Evening check
        
        # Also run once immediately for testing
        logger.info("Running initial check...")
        self.check_and_post_cameras()
        
        # Keep the bot running
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
                
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                time.sleep(60)  # Wait 1 minute before retrying


if __name__ == "__main__":
    # Check for --once flag for manual testing
    run_once = '--once' in sys.argv
    
    bot = COTripBot()
    
    if run_once:
        bot.run_once()
    else:
        bot.run_continuous()
