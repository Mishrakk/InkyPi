from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image
from io import BytesIO
import requests
import logging
import subprocess
import tempfile
import zipfile
import os
import csv
from datetime import datetime

logger = logging.getLogger(__name__)


class MpkPoznan(BasePlugin):
    def generate_settings_template(self):

        template_params = super().generate_settings_template()
        template_params["style_settings"] = False
        return template_params

    def generate_image(self, settings, device_config):
        stop_code = "OJLY02"
        routes = ["151", "185", "190", "193"]

        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = self.fetch_data(temp_dir)
            feed_info = self.get_feed_info(data_path)
            stop_info = self.get_stop_info(stop_code, data_path)
            current_time = self.get_current_time()
            current_service_id = self.get_service_id(data_path)
            routes_info = {
                route: self.get_route_info(
                    route, stop_info["stop_id"], current_service_id, data_path
                )
                for route in routes
            }

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        template_params = {
            "title": settings.get("title"),
            "plugin_settings": settings,
            "feed_info": feed_info,
            "stop_info": stop_info,
            "current_time": current_time,
            "routes_info": routes_info,
        }
        logger.info(f"Template params: {template_params}")

        image = self.render_image(
            dimensions, "mpk_poznan.html", "mpk_poznan.css", template_params
        )
        return image

    def fetch_data(self, temp_dir):
        """Download GTFS zip file and extract to temporary location."""
        try:
            zip_path = os.path.join(temp_dir, "ZTMPoznanGTFS.zip")

            # Download the zip file using curl
            url = "https://www.ztm.poznan.pl/pl/dla-deweloperow/getGTFSFile"
            headers = {
                "Accept": "application/octet-stream",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # Write the zip file to disk
            with open(zip_path, "wb") as f:
                f.write(response.content)

            # Extract the zip file to the temp directory
            extract_dir = os.path.join(temp_dir, "GTFS")
            os.makedirs(extract_dir, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

            logger.info(f"GTFS data downloaded and extracted to: {extract_dir}")
            return extract_dir

        except requests.RequestException as e:
            logger.error(f"Error downloading GTFS file: {e}")
            return None
        except zipfile.BadZipFile as e:
            logger.error(f"Error extracting zip file: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in fetch_data: {e}")
            return None

    def get_feed_info(self, data_path):
        try:
            feed_info_file = os.path.join(data_path, "feed_info.txt")
            with open(feed_info_file, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    return {
                        "valid_from": datetime.strptime(
                            row.get("feed_start_date"), "%Y%m%d"
                        ).strftime("%d-%m-%Y"),
                        "valid_to": datetime.strptime(
                            row.get("feed_end_date"), "%Y%m%d"
                        ).strftime("%d-%m-%Y"),
                    }
        except Exception as e:
            logger.error(f"Error parsing feed_info.txt: {e}")
            return {}

    def get_stop_info(self, stop_code, data_path):
        try:
            stops_file = os.path.join(data_path, "stops.txt")
            with open(stops_file, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row["stop_code"] == stop_code:
                        return row
        except Exception as e:
            logger.error(f"Error parsing stops.txt: {e}")
            return {}

    def get_route_info(self, route_name, stop_id, current_service_id, data_path):
        route_info = {}
        try:
            routes_file = os.path.join(data_path, "routes.txt")
            with open(routes_file, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row["route_short_name"] == route_name:
                        route_info = row
                        break
        except Exception as e:
            logger.error(f"Error parsing routes.txt: {e}")
            return {}
        trips = []
        try:
            trips_file = os.path.join(data_path, "trips.txt")
            with open(trips_file, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                trips = [
                    row
                    for row in reader
                    if row["route_id"] == route_info.get("route_id")
                    and row["service_id"] == current_service_id
                ]
        except Exception as e:
            logger.error(f"Error parsing trips.txt: {e}")
            return {}
        try:
            stop_times_file = os.path.join(data_path, "stop_times.txt")
            with open(stop_times_file, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                stop_times_data = [
                    row
                    for row in reader
                    if row["stop_id"] == stop_id
                    and row["trip_id"] in [trip["trip_id"] for trip in trips]
                ]
                route_info["headsign"] = stop_times_data[0]["stop_headsign"]
                stop_times = [row["departure_time"] for row in stop_times_data]
                route_info["stop_times"] = self.get_parsed_stop_times(stop_times)
        except Exception as e:
            logger.error(f"Error parsing stop_times.txt: {e}")
            return {}
        return route_info

    def get_parsed_stop_times(self, stop_times):
        parsed_times = {}
        for time_str in stop_times:
            try:
                hour, minute, _ = map(int, time_str.split(":"))
                parsed_times.setdefault(hour, []).append(minute)
            except ValueError:
                logger.error(f"Invalid time format: {time_str}")
        for hour in parsed_times:
            parsed_times[hour].sort()
        return parsed_times

    def get_current_time(self):
        """Get current time information as a structured object."""
        now = datetime.now()
        day_of_week = now.strftime("%A").lower()
        return {
            "day_of_week": day_of_week,
            "day_of_week_translated": self.get_translated_day_of_week(day_of_week),
            "time": now.strftime("%H:%M"),
            "date": now.strftime("%d-%m-%Y"),
        }

    def get_translated_day_of_week(self, day_of_week):
        translations = {
            "monday": "poniedziałek",
            "tuesday": "wtorek",
            "wednesday": "środa",
            "thursday": "czwartek",
            "friday": "piątek",
            "saturday": "sobota",
            "sunday": "niedziela",
        }
        return translations.get(day_of_week.lower(), day_of_week)

    def get_service_id(self, data_path):
        current_day = datetime.now().strftime("%A").lower()
        try:
            calendar_file = os.path.join(data_path, "calendar.txt")
            with open(calendar_file, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    if row[current_day] == "1":
                        return row["service_id"]
        except Exception as e:
            logger.error(f"Error parsing calendar.txt: {e}")
            return {}
