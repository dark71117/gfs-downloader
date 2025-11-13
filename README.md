# GFS Weather Data Downloader

Automatic downloader for GFS (Global Forecast System) weather data with MySQL database integration.

## Features

- 📡 Downloads latest GFS forecast data from NOAA
- 🌍 Configurable geographic region
- 🗄️ Automatic MySQL database storage
- 📊 ~20 weather parameters including:
  - Temperature, humidity, wind
  - Pressure, precipitation
  - Cloud cover, visibility
  - CAPE, CIN (for storms)
- 🔄 Old forecast cleanup
- 🚀 Easy Windows integration

## Quick Start

1. Install Python 3.9+
2. Install XAMPP (MySQL)
3. Extract files
4. Run: `pip install -r requirements.txt`
5. Import `setup_database.sql` to MySQL
6. Configure `config.ini`
7. Run: `python gfs_downloader.py` or `uruchom.bat`

## Files

- `gfs_downloader.py` - Main script
- `config.ini` - Configuration file
- `requirements.txt` - Python dependencies
- `setup_database.sql` - Database schema
- `uruchom.bat` - Windows launcher
- `INSTRUKCJA.md` - Detailed Polish guide

## Configuration

Edit `config.ini`:

```ini
[database]
user = root
password = 
host = localhost
database = dane_gfs

[region]
lat_min = 49.0
lat_max = 55.0
lon_min = 14.0
lon_max = 24.0
```

## Database Schema

Table: `gfs_forecast`

Main columns:
- `lat`, `lon` - Location coordinates
- `forecast_time` - Forecast valid time
- `run_time` - Model run time
- `t2m` - Temperature (°C)
- `wind_speed` - Wind speed (m/s)
- `mslp` - Pressure (hPa)
- `tp` - Precipitation (mm)
- ... and more

## Laravel Integration

```php
$weather = DB::table('gfs_forecast')
    ->where('lat', '>=', $lat - 0.25)
    ->where('lat', '<=', $lat + 0.25)
    ->orderBy('forecast_time')
    ->get();
```

## Requirements

- Python 3.9+
- MySQL 5.7+
- ~500 MB disk space
- Internet connection

## Troubleshooting

See `INSTRUKCJA.md` for detailed troubleshooting guide (Polish).

## License

MIT License

## Credits

- GFS data: NOAA/NCEP
- cfgrib: ECMWF
