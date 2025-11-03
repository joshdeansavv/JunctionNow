import requests
import json
import datetime
import io
from typing import Dict, List, Optional

class WeatherData:
    def __init__(self):
        self.latitude = 39.0639
        self.longitude = -108.5506
        self.weather_api_base = "https://api.weather.gov"
        self.discord_webhooks = [
            "YOUR_DISCORD_WEBHOOK_URL_HERE"
        ]

        self.headers = {
            'User-Agent': 'Mesa County Weather Script (weather@example.com)',
            'Accept': 'application/geo+json, application/ld+json'
        }
        
        # Wind direction mapping
        self.wind_directions = {
            0: "N", 45: "NE", 90: "E", 135: "SE",
            180: "S", 225: "SW", 270: "W", 315: "NW", 360: "N"
        }

    def make_request(self, url: str) -> Dict:
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return {}

    def get_grid_coordinates(self) -> Dict:
        url = f"{self.weather_api_base}/points/{self.latitude},{self.longitude}"
        return self.make_request(url)

    def get_current_conditions(self) -> Dict:
        grid_data = self.get_grid_coordinates()
        if 'properties' not in grid_data:
            return {}

        stations_url = grid_data['properties'].get('observationStations')
        if not stations_url:
            return {}

        stations_data = self.make_request(stations_url)
        if 'features' not in stations_data or not stations_data['features']:
            return {}

        station_id = stations_data['features'][0]['properties']['stationIdentifier']
        url = f"{self.weather_api_base}/stations/{station_id}/observations/latest"
        return self.make_request(url)

    def get_forecast(self) -> Dict:
        grid_data = self.get_grid_coordinates()
        if 'properties' not in grid_data:
            return {}

        grid_id = grid_data['properties']['gridId']
        grid_x = grid_data['properties']['gridX']
        grid_y = grid_data['properties']['gridY']

        url = f"{self.weather_api_base}/gridpoints/{grid_id}/{grid_x},{grid_y}/forecast"
        return self.make_request(url)

    def get_alerts(self) -> Dict:
        url = f"{self.weather_api_base}/alerts/active?zone=COZ006"
        return self.make_request(url)
    
    def get_hazardous_weather_outlook(self) -> str:
        """Get hazardous weather outlook for the area"""
        grid_data = self.get_grid_coordinates()
        if 'properties' not in grid_data:
            return ""
        
        forecast_office = grid_data['properties'].get('cwa', 'GJT')
        url = f"{self.weather_api_base}/products/types/HWO/locations/{forecast_office}"
        
        try:
            data = self.make_request(url)
            if 'graph' in data and data['graph']:
                product_id = data['graph'][0]['@id']
                product_data = self.make_request(product_id)
                if 'productText' in product_data:
                    return product_data['productText']
        except Exception as e:
            print(f"Error getting HWO: {e}")
        
        return ""
    
    def convert_wind_direction(self, degrees: Optional[float]) -> str:
        """Convert wind direction in degrees to cardinal direction"""
        if degrees is None:
            return "N/A"
        
        # Round to nearest 45 degrees
        rounded = round(degrees / 45) * 45
        if rounded == 360:
            rounded = 0
        
        return self.wind_directions.get(rounded, f"{int(degrees)}°")
    
    def meters_per_second_to_mph(self, mps: Optional[float]) -> Optional[float]:
        """Convert meters per second to miles per hour"""
        if mps is None:
            return None
        return mps * 2.23694
    
    def celsius_to_fahrenheit(self, celsius: Optional[float]) -> Optional[float]:
        """Convert Celsius to Fahrenheit"""
        if celsius is None:
            return None
        return (celsius * 9/5) + 32
    
    def pascals_to_inches_hg(self, pascals: Optional[float]) -> Optional[float]:
        """Convert pascals to inches of mercury"""
        if pascals is None:
            return None
        return pascals * 0.0002953
    
    def meters_to_miles(self, meters: Optional[float]) -> Optional[float]:
        """Convert meters to miles"""
        if meters is None:
            return None
        return meters * 0.000621371
    
    def calculate_heat_index(self, temp_f: float, humidity: float) -> Optional[float]:
        """Calculate heat index in Fahrenheit"""
        if temp_f < 80:
            return None
        
        # Rothfusz regression
        hi = -42.379 + 2.04901523*temp_f + 10.14333127*humidity
        hi += -0.22475541*temp_f*humidity + -0.00683783*temp_f*temp_f
        hi += -0.05481717*humidity*humidity + 0.00122874*temp_f*temp_f*humidity
        hi += 0.00085282*temp_f*humidity*humidity + -0.00000199*temp_f*temp_f*humidity*humidity
        
        return hi
    
    def calculate_wind_chill(self, temp_f: float, wind_mph: float) -> Optional[float]:
        """Calculate wind chill in Fahrenheit"""
        if temp_f > 50 or wind_mph < 3:
            return None
        
        wc = 35.74 + 0.6215*temp_f - 35.75*(wind_mph**0.16) + 0.4275*temp_f*(wind_mph**0.16)
        return wc

    def get_radar_image(self) -> tuple[bytes, str]:
        url = "https://radar.weather.gov/ridge/standard/KGJX_loop.gif"

        try:
            print(f"Getting radar from: {url}")
            response = requests.get(url, timeout=15)
            if response.status_code == 200 and len(response.content) < 6 * 1024 * 1024:
                print(f"Got radar ({len(response.content)/1024:.1f} KB)")
                return response.content, url
            else:
                print(f"Failed: {response.status_code}")
        except Exception as e:
            print(f"Error: {e}")

        return b"", ""

    def create_concise_embed(self, weather_data: Dict, radar_available: bool, radar_url: str = None) -> Dict:
        current_data = self.get_current_conditions()
        
        # Initialize all variables
        temp = "N/A"
        temp_f_val = None
        conditions = "N/A"
        wind_speed = "N/A"
        wind_speed_mph_val = None
        wind_direction = "N/A"
        wind_gust = ""
        humidity = "N/A"
        humidity_val = None
        dewpoint = "N/A"
        pressure = "N/A"
        visibility = "N/A"
        feels_like = ""

        # Parse current conditions
        if 'properties' in current_data:
            props = current_data['properties']
            
            # Temperature
            temp_c = props.get('temperature', {}).get('value')
            if temp_c is not None:
                temp_f_val = self.celsius_to_fahrenheit(temp_c)
                temp = f"{temp_f_val:.0f}°F"
            
            # Conditions - try multiple fields
            conditions = (props.get('textDescription') or 
                         props.get('weather') or 
                         props.get('shortForecast') or 
                         "Clear")
            
            # Wind
            wind_speed_mps = props.get('windSpeed', {}).get('value')
            if wind_speed_mps is not None:
                wind_speed_mph_val = self.meters_per_second_to_mph(wind_speed_mps)
                wind_speed = f"{wind_speed_mph_val:.0f} mph"
            
            wind_dir_deg = props.get('windDirection', {}).get('value')
            if wind_dir_deg is not None:
                wind_direction = self.convert_wind_direction(wind_dir_deg)
            
            wind_gust_mps = props.get('windGust', {}).get('value')
            if wind_gust_mps is not None and wind_gust_mps > 0:
                wind_gust_mph = self.meters_per_second_to_mph(wind_gust_mps)
                wind_gust = f" (Gusts {wind_gust_mph:.0f} mph)"
            
            # Humidity
            humidity_val = props.get('relativeHumidity', {}).get('value')
            if humidity_val is not None:
                humidity = f"{humidity_val:.0f}%"
            
            # Calculate feels like temperature
            if temp_f_val is not None and humidity_val is not None:
                heat_index = self.calculate_heat_index(temp_f_val, humidity_val)
                if heat_index and heat_index - temp_f_val > 5:
                    feels_like = f" (Feels like {heat_index:.0f}°F)"
            
            if temp_f_val is not None and wind_speed_mph_val is not None:
                wind_chill = self.calculate_wind_chill(temp_f_val, wind_speed_mph_val)
                if wind_chill and temp_f_val - wind_chill > 5:
                    feels_like = f" (Feels like {wind_chill:.0f}°F)"
            
            # Dewpoint
            dewpoint_c = props.get('dewpoint', {}).get('value')
            if dewpoint_c is not None:
                dewpoint_f = self.celsius_to_fahrenheit(dewpoint_c)
                dewpoint = f"{dewpoint_f:.0f}°F"
            
            # Pressure
            pressure_pa = props.get('barometricPressure', {}).get('value')
            if pressure_pa is not None:
                pressure_inhg = self.pascals_to_inches_hg(pressure_pa)
                pressure = f"{pressure_inhg:.2f} inHg"
            
            # Visibility
            visibility_m = props.get('visibility', {}).get('value')
            if visibility_m is not None:
                visibility_mi = self.meters_to_miles(visibility_m)
                visibility = f"{visibility_mi:.1f} mi"

        # Get forecast
        forecast_data = self.get_forecast()
        today_forecast = "No forecast available"
        extended_forecast = []

        if 'properties' in forecast_data:
            periods = forecast_data['properties'].get('periods', [])
            if periods:
                # Today's forecast
                today = periods[0]
                today_temp = today.get('temperature', 'N/A')
                today_conditions = today.get('shortForecast', 'N/A')
                today_forecast = f"{today_temp}°F - {today_conditions}"
                
                # Extended forecast (next 3 periods)
                for period in periods[1:4]:
                    name = period.get('name', '')
                    temp_val = period.get('temperature', '')
                    forecast = period.get('shortForecast', '')
                    extended_forecast.append(f"**{name}**: {temp_val}°F - {forecast}")

        # Get alerts
        alerts_data = self.get_alerts()
        alerts_text = "No active alerts"
        alert_details = []

        if 'features' in alerts_data and alerts_data['features']:
            alerts_text = f"⚠️ {len(alerts_data['features'])} active alert(s)"
            for alert in alerts_data['features'][:3]:  # Show up to 3 alerts
                event = alert['properties'].get('event', 'Alert')
                severity = alert['properties'].get('severity', '')
                alert_details.append(f"• {event} ({severity})")

        # Build embed description to match requested format
        description = f"Today's Forecast: {today_forecast}\n\n"
        description += f"**Current:** {temp}{feels_like} - {conditions}\n"
        description += f"**Wind:** {wind_direction} at {wind_speed}{wind_gust}\n"
        description += f"**Humidity:** {humidity}\n"
        
        # Only add dewpoint if we have the data
        if dewpoint != "N/A":
            description += f"**Dewpoint:** {dewpoint}\n"
        
        # Only add pressure if we have the data
        if pressure != "N/A":
            description += f"**Pressure:** {pressure}\n"
        
        # Only add visibility if we have the data
        if visibility != "N/A":
            description += f"**Visibility:** {visibility}\n"
        
        description += "\n"

        # Only show alerts section if there are alerts
        if alert_details:
            description += "**Alerts**\n"
            description += "\n".join(alert_details)

        # Always use blue color (#0086cc)
        embed_color = 35796

        embed = {
            "title": "Mesa County Radar",
            "description": description,
            "color": embed_color,
            "fields": []
        }

        if radar_available and radar_url:
            embed["image"] = {"url": "attachment://radar.gif"}

        return embed

    def send_to_discord(self, embed: Dict, radar_gif: bytes):
        try:
            files = {}
            payload = {"embeds": [embed], "components": []}
            data = {"payload_json": json.dumps(payload)}

            if radar_gif:
                files = {"file": ("radar.gif", io.BytesIO(radar_gif), "image/gif")}
                print(f"Sending radar image ({len(radar_gif)/1024:.1f} KB)")
            else:
                print("Sending weather data only (no radar image)")

            for webhook in self.discord_webhooks:
                try:
                    if radar_gif:
                        files = {"file": ("radar.gif", io.BytesIO(radar_gif), "image/gif")}
                    response = requests.post(webhook, data=data, files=files, timeout=30)
                    if response.status_code in [200, 204]:
                        print(f"Weather data sent to Discord webhook")
                    else:
                        print(f"Discord error: {response.status_code} - {response.text}")
                except Exception as e:
                    print(f"Error sending to webhook: {e}")
        except Exception as e:
            print(f"Error sending to Discord: {e}")

    def run(self, send_discord: bool = False, verbose: bool = False):
        print("Getting Mesa County weather data...")

        weather_data = self.get_forecast()
        radar_gif, radar_url = self.get_radar_image()
        radar_available = bool(radar_gif)

        if radar_available:
            print("Got radar imagery")

        embed = self.create_concise_embed(weather_data, radar_available, radar_url)
        
        if verbose:
            print("\n" + "="*60)
            print("WEATHER EMBED PREVIEW")
            print("="*60)
            print(f"Title: {embed['title']}")
            print(f"\n{embed['description']}")
            print("="*60 + "\n")

        if send_discord:
            self.send_to_discord(embed, radar_gif)

        print("Weather script completed")

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Mesa County Weather Script')
    parser.add_argument('--discord', action='store_true', help='Send to Discord')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')

    args = parser.parse_args()

    weather = WeatherData()
    weather.run(send_discord=args.discord, verbose=args.verbose)

if __name__ == "__main__":
    main()
