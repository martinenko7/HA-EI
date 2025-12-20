# Home Assistant Electric Ireland Integration for Smart Tariff Plans

[![GitHub issues](https://img.shields.io/github/issues/martinenko7/HA-EI)](https://github.com/martinenko7/HA-EI/issues)
[![GitHub](https://img.shields.io/github/license/martinenko7/HA-EI)](https://github.com/martinenko7/HA-EI/blob/main/LICENSE.txt)

Home Assistant integration with **Electric Ireland Insights** for Smart TOU (Time of Use) tariffs.

## Features

* 📊 **Total Energy Consumption & Cost**: Overall electricity usage and cost across all tariff periods
* 🌙 **Night Rate (Off-Peak)**: Consumption and cost for 23:00-08:00 period at reduced rate
* ☀️ **Day Rate (Mid-Peak)**: Consumption and cost for 08:00-17:00 and 19:00-23:00 at standard rate
* ⚡ **Peak Rate (On-Peak)**: Consumption and cost for 17:00-19:00 at premium rate
* 📈 **Energy Dashboard Integration**: All sensors automatically feed into Home Assistant's Energy Dashboard with historical statistics
* 🕐 **Hourly Data**: Consumption reported in 1-hour intervals with accurate tariff classification


## FAQs

### How does it work?

It basically scrapes the Insights page that Electric Ireland provides. It will first mimic a user login interaction,
and then will navigate to the page to fetch the data.

As this data is also feed from ESB ([Electrical Supply Board](https://esb.ie)), it is not in real time. They publish
data with 1-3 days delay; this integration takes care of that and will fetch every hour and ingest data dated back up
to 10 days. This job runs every hour, so whenever it gets published it should get feed into Home Assistant within 60
minutes.

### Why not fetching from ESB directly?

I have Electric Ireland, and ESB has a captcha in their login. I just didn't want to bother to investigate how to
bypass it.

### Why not applying the 30% Off DD discount?

This is tariff-dependant. The Electric Ireland API reports cost as per tariff price (24h, smart, etc.), so in case some
tariff does not offer the 30% Off Direct Debit, this integration will apply a transformation incorrect for the user.

So, in summary: Cost reports gross usage cost with VAT, without discount but also without standing charge or levy.

### Why does the individual reporte device sometimes exceed the reported usage in Electric Ireland?

I don't have a clear answer to this. I have noticed this in some buckets, but there it is an issue in how the metrics
are reported into buckets. It is an issue either in ESB / Electric Ireland reporting, that they report the intervals
incorrectly; or it is the device meters that they may do the same.

In either case, I would not expect the total amount to differ: it is just a matter of consumption/cost being reported
into the wrong hour. If you take the previous and after, the total should be the same.

## Technical Details

### Sensors

This integration creates 8 sensors:

#### Total Sensors (All Tariffs Combined)
* **Electric Ireland Consumption**: Total energy consumption in kWh
* **Electric Ireland Cost**: Total cost in EUR

#### Tariff-Specific Sensors (Time of Use)
* **Electric Ireland Consumption Night Rate**: kWh consumed during off-peak hours (23:00-08:00)
* **Electric Ireland Cost Night Rate**: Cost in EUR for off-peak usage
* **Electric Ireland Consumption Day Rate**: kWh consumed during mid-peak hours (08:00-17:00, 19:00-23:00)
* **Electric Ireland Cost Day Rate**: Cost in EUR for mid-peak usage
* **Electric Ireland Consumption Peak Rate**: kWh consumed during on-peak hours (17:00-19:00)
* **Electric Ireland Cost Peak Rate**: Cost in EUR for on-peak usage

**Note**: Cost values are gross usage costs with VAT included, but **without** the 30% Direct Debit discount, standing charges, or PSO levy.

### Data Retrieval Flow

1. Open a `requests` session against Electric Ireland website, and:
    1. Create a GET request to retrieve the cookies and the state.
    2. Do a POST request to login into Electric Ireland.
    3. Scrape the dashboard to try to find the `div` with the target Account Number.
    4. Navigate to the Insights page for that Account Number.
2. Now, once we have that Insights page, we don't need the ELectric Ireland session anymore:
    1. The page contains a payload to call Bidgely API (data API provider for Electric Ireland).
    2. Authenticate using that payload against Bidgely API (no need for session or cookies).
    3. Send requests to the API to fetch the data for required intervals.
    4. Profit! 🎉

### Schedule

Every hour:

* Authenticates with Electric Ireland and retrieves API credentials
* Fetches data for the last 30 days in parallel batches (5 days at a time for efficiency)
* Each day returns hourly datapoints with consumption and cost values
* Datapoints are classified by tariff type based on time of day:
  - **23:00-08:00** → Off-Peak (Night Rate)
  - **17:00-19:00** → On-Peak (Peak Rate)
  - **08:00-17:00 & 19:00-23:00** → Mid-Peak (Day Rate)
* Historical statistics are imported and immediately available in the Energy Dashboard
## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add `https://github.com/martinenko7/HA-EI` as an Integration
6. Click "Install"
7. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/electric_ireland_smart_tariff` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

### Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "Electric Ireland Insights"
4. Enter your Electric Ireland username, password, and account number
5. The sensors will appear and start collecting historical data

## Support

For issues, feature requests, or questions, please visit:
- **GitHub Issues**: [https://github.com/martinenko7/HA-EI/issues](https://github.com/martinenko7/HA-EI/issues)
- **GitHub Repository**: [https://github.com/martinenko7/HA-EI](https://github.com/martinenko7/HA-EI)

## Acknowledgements

* [Historical sensors for Home Assistant](https://github.com/ldotlopez/ha-historical-sensor): Provides the library for importing historical statistics
* Original integration by [barreeeiroo](https://github.com/barreeeiroo/Home-Assistant-Electric-Ireland)ub.com/ldotlopez/ha-historical-sensor)
