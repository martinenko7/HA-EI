DOMAIN = "electric_ireland_insights"
NAME = "Electric Ireland Insights"

LOOKUP_DAYS = 30
PARALLEL_DAYS = 5

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
