DOMAIN = "electric_ireland_smart_tariff"
NAME = "Electric Ireland Smart Tariff Insights"

# Data fetching configuration
LOOKUP_DAYS = 30  # Initial historical data to fetch on first run
ONGOING_LOOKUP_DAYS = 3  # Only check last 3 days on subsequent updates (Electric Ireland has 1-3 day delay)
PARALLEL_DAYS = 5  # Number of days to fetch in parallel
MIN_UPDATE_INTERVAL_HOURS = 6  # Minimum hours between full data fetches to avoid rate limiting

# Tariff types from Electric Ireland API
TARIFF_FLAT_RATE = "flatRate"
TARIFF_OFF_PEAK = "offPeak"      # Night rate
TARIFF_MID_PEAK = "midPeak"      # Day rate  
TARIFF_ON_PEAK = "onPeak"        # Peak rate

# All available tariffs
TARIFF_TYPES = [TARIFF_FLAT_RATE, TARIFF_OFF_PEAK, TARIFF_MID_PEAK, TARIFF_ON_PEAK]

# User-friendly tariff names
TARIFF_NAMES = {
    TARIFF_FLAT_RATE: "Flat Rate",
    TARIFF_OFF_PEAK: "Night Rate",
    TARIFF_MID_PEAK: "Day Rate",
    TARIFF_ON_PEAK: "Peak Rate",
}
