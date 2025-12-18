import logging
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from requests import RequestException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .const import DOMAIN


LOGGER = logging.getLogger(DOMAIN)

BASE_URL = "https://youraccountonline.electricireland.ie"

# Request timeout in seconds (connect, read)
REQUEST_TIMEOUT = (10, 30)

# Browser-like headers to avoid being blocked
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def create_session_with_retries():
    """Create a requests session with retry logic and proper configuration."""
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,  # Total number of retries
        backoff_factor=1,  # Wait 1s, 2s, 4s between retries
        status_forcelist=[429, 500, 502, 503, 504],  # Retry on these HTTP status codes
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Set default headers
    session.headers.update(DEFAULT_HEADERS)
    
    return session


class ElectricIrelandScraper:
    def __init__(self, username, password, account_number):
        self.__scraper = None

        self.__username = username
        self.__password = password
        self.__account_number = account_number

    def refresh_credentials(self):
        LOGGER.info("Trying to refresh credentials...")
        session = create_session_with_retries()

        meter_ids = self.__login_and_get_meter_ids(session)
        if not meter_ids:
            return

        self.__scraper = MeterInsightScraper(session, meter_ids)

    @property
    def scraper(self):
        return self.__scraper

    def __login_and_get_meter_ids(self, session):
        # REQUEST 1: Get the Source token, and initialize the session
        LOGGER.debug("Getting Source Token...")
        try:
            res1 = session.get(f"{BASE_URL}/", timeout=REQUEST_TIMEOUT)
            res1.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to connect to home page: {err}")
            LOGGER.debug(f"Full error details: {type(err).__name__}: {err}")
            return None

        soup1 = BeautifulSoup(res1.text, "html.parser")
        source_input = soup1.find('input', attrs={'name': 'Source'})
        source = source_input.get('value') if source_input else None
        rvt = session.cookies.get_dict().get("rvt")

        if not source:
            LOGGER.error("SCRAPE FAIL: Could not find 'Source' hidden field on login page.")
            return None
        if not rvt:
            LOGGER.error("SCRAPE FAIL: Could not find 'rvt' cookie.")
            return None

        # REQUEST 2: Perform Login
        LOGGER.debug("Performing Login...")
        
        # Add a small delay to avoid being flagged as a bot
        time.sleep(0.5)
        
        try:
            res2 = session.post(
                f"{BASE_URL}/",
                data={
                    "LoginFormData.UserName": self.__username,
                    "LoginFormData.Password": self.__password,
                    "rvt": rvt,
                    "Source": source,
                    "PotText": "",
                    "__EiTokPotText": "",
                    "ReturnUrl": "",
                    "AccountNumber": "",
                },
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            res2.raise_for_status()
        except requests.exceptions.Timeout as err:
            LOGGER.error(f"Login POST request timed out: {err}")
            LOGGER.info("The Electric Ireland website may be slow. Try again later.")
            return None
        except requests.exceptions.ConnectionError as err:
            LOGGER.error(f"Connection error during login: {err}")
            LOGGER.info("Check your network connection or the Electric Ireland website may be down.")
            return None
        except RequestException as err:
            LOGGER.error(f"Login POST request failed: {err}")
            LOGGER.debug(f"Full error details: {type(err).__name__}: {err}")
            return None

        # --- SPY CODE: Check if we are still on the login page ---
        if "LoginFormData.UserName" in res2.text or "Log in" in res2.text:
            LOGGER.error("LOGIN FAILED: The website returned the login page again.")
            
            # Try to find the specific error message from the site
            soup_debug = BeautifulSoup(res2.text, "html.parser")
            # Look for common error classes used by Electric Ireland
            error_msg = soup_debug.find(class_="field-validation-error") or \
                        soup_debug.find(class_="validation-summary-errors")
            
            if error_msg:
                LOGGER.error(f"WEBSITE ERROR MESSAGE: {error_msg.get_text(strip=True)}")
            else:
                LOGGER.error("Could not find a specific error message. Check credentials.")
            return None
        # -------------

        soup2 = BeautifulSoup(res2.text, "html.parser")
        account_divs = soup2.find_all("div", {"class": "my-accounts__item"})
        
        # Debug: How many accounts did we find?
        LOGGER.debug(f"Scraper found {len(account_divs)} accounts on the dashboard.")

        target_account = None
        for account_div in account_divs:
            account_number_el = account_div.find("p", {"class": "account-number"})
            if not account_number_el:
                continue
            
            account_number = account_number_el.text.strip() # Added strip() just in case
            
            # Check if this is the account we want
            if account_number != self.__account_number:
                LOGGER.debug(f"Skipping account {account_number} (looking for {self.__account_number})")
                continue

            is_elec_divs = account_div.find_all("h2", {"class": "account-electricity-icon"})
            if len(is_elec_divs) != 1:
                LOGGER.info(f"Found account {account_number} but it does not appear to be an Electricity account.")
                continue

            target_account = account_div
            break

        if not target_account:
            LOGGER.warning(f"Failed to find Target Account ({self.__account_number}) in the list. Login might have been partial.")
            return None

        # REQUEST 3: Navigate to Insights page to get meter IDs
        LOGGER.debug("Navigating to Insights page...")
        event_form = target_account.find("form", {"action": "/Accounts/OnEvent"})
        
        if not event_form:
            LOGGER.error("Failed to find the 'OnEvent' form to click 'View Insights'. HTML structure might have changed.")
            return None

        req3 = {"triggers_event": "AccountSelection.ToInsights"}
        for form_input in event_form.find_all("input"):
            req3[form_input.get("name")] = form_input.get("value")

        try:
            res3 = session.post(f"{BASE_URL}/Accounts/OnEvent", data=req3, timeout=REQUEST_TIMEOUT)
            res3.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Navigate to Insights: {err}")
            LOGGER.debug(f"Full error details: {type(err).__name__}: {err}")
            return None

        # Extract meter IDs from #modelData div
        soup3 = BeautifulSoup(res3.text, "html.parser")
        model_data = soup3.find("div", {"id": "modelData"})
        
        if not model_data:
            LOGGER.error("Failed to find 'modelData' div on Insights page. We might be on the wrong page.")
            return None

        partner = model_data.get("data-partner")
        contract = model_data.get("data-contract")
        premise = model_data.get("data-premise")

        if not all([partner, contract, premise]):
            LOGGER.error(f"Missing meter IDs: partner={partner}, contract={contract}, premise={premise}")
            return None

        LOGGER.info(f"SUCCESS: Found meter IDs: partner={partner}, contract={contract}, premise={premise}")
        return {"partner": partner, "contract": contract, "premise": premise}

class MeterInsightScraper:
    """Scraper for the new Electric Ireland MeterInsight API."""

    def __init__(self, session, meter_ids):
        self.__session = session
        self.__partner = meter_ids["partner"]
        self.__contract = meter_ids["contract"]
        self.__premise = meter_ids["premise"]

    def get_data(self, target_date, tariff_type=None):
        """Fetch hourly usage data for a specific date.

        Args:
            target_date: The date to fetch data for
            tariff_type: Optional - specific tariff to filter (flatRate, offPeak, midPeak, onPeak)
                        If None, returns data for all available tariffs

        Returns:
            List of datapoints with 'consumption', 'cost', 'intervalEnd', and 'tariff' keys
        """
        date_str = target_date.strftime("%Y-%m-%d")
        tariff_filter = f" (tariff: {tariff_type})" if tariff_type else " (all tariffs)"
        LOGGER.debug(f"Getting hourly data for {date_str}{tariff_filter}...")

        url = f"{BASE_URL}/MeterInsight/{self.__partner}/{self.__contract}/{self.__premise}/hourly-usage"

        try:
            response = self.__session.get(url, params={"date": date_str}, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to get hourly usage data for {date_str}: {err}")
            LOGGER.debug(f"Full error details: {type(err).__name__}: {err}")
            return []

        # Check if we got JSON or an error page
        content_type = response.headers.get('content-type', '')
        if 'application/json' not in content_type:
            LOGGER.error(f"Expected JSON but got {content_type}. Response: {response.text[:500]}")
            return []

        try:
            data = response.json()
        except Exception as err:
            LOGGER.error(f"Failed to parse JSON: {err}. Response: {response.text[:500]}")
            return []

        if not data.get("isSuccess"):
            LOGGER.error(f"API returned error: {data.get('message')}")
            return []

        raw_datapoints = data.get("data", [])
        LOGGER.debug(f"Found {len(raw_datapoints)} hourly datapoints for {date_str}")

        # Transform to expected format with 'consumption', 'cost', 'intervalEnd', and 'tariff'
        datapoints = []

        # Tariff buckets as seen in response on Smart TOU plan
        usage_tariff_keys = ("flatRate", "offPeak", "midPeak", "onPeak")
        
        for dp in raw_datapoints:
            end_date_str = dp.get("endDate")

            if not end_date_str:
                continue

            # Parse ISO date and convert to Unix timestamp
            # Format: "2025-12-01T00:59:59Z"
            try:
                end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                interval_end = int(end_dt.timestamp())
            except (ValueError, AttributeError) as err:
                LOGGER.warning(f"Failed to parse date {end_date_str}: {err}")
                continue

            # Determine which tariff is active based on time of day
            # Time ranges: Off Peak (Night) 23:00-08:00, On Peak (Peak) 17:00-19:00, Mid Peak (Day) 08:00-17:00 & 19:00-23:00
            hour = end_dt.hour
            
            # Determine the expected active tariff based on hour
            if hour >= 23 or hour < 8:  # 23:00-07:59
                expected_tariff = "offPeak"  # Night rate
            elif 17 <= hour < 19:  # 17:00-18:59
                expected_tariff = "onPeak"   # Peak rate
            else:  # 08:00-16:59 and 19:00-22:59
                expected_tariff = "midPeak"  # Day rate
            
            # Process tariff buckets
            # If filtering for a specific tariff, only get that one
            # If not filtering, use the time-based expected tariff to avoid double-counting
            
            if tariff_type:
                # Filtering mode: only get the requested tariff
                target_tariff = tariff_type
            else:
                # Total mode: use the tariff that should be active at this hour
                target_tariff = expected_tariff
            
            # Get the data for the target tariff
            usage_entry = dp.get(target_tariff)
            
            if usage_entry is not None:
                consumption = usage_entry.get("consumption")
                cost = usage_entry.get("cost")
                
                # Only add if there's actual data
                if consumption not in (None, 0) or cost not in (None, 0):
                    datapoints.append({
                        "consumption": consumption,
                        "cost"       : cost,
                        "intervalEnd": interval_end,
                        "tariff"     : target_tariff,
                    })

        return datapoints