<?php
/**
 * Przykłady użycia danych GFS w Laravel
 * 
 * Skopiuj te funkcje do swojego kontrolera
 */

namespace App\Http\Controllers;

use Illuminate\Support\Facades\DB;
use Illuminate\Http\Request;

class WeatherController extends Controller
{
    /**
     * Pobierz prognozę dla konkretnej lokalizacji
     * 
     * @param float $lat - szerokość geograficzna (np. 52.23 dla Warszawy)
     * @param float $lon - długość geograficzna (np. 21.01 dla Warszawy)
     * @return array
     */
    public function getForecastForLocation($lat, $lon)
    {
        // Promień wyszukiwania (0.25 stopnia ≈ 28 km)
        $radius = 0.25;
        
        $forecast = DB::table('gfs_forecast')
            ->where('lat', '>=', $lat - $radius)
            ->where('lat', '<=', $lat + $radius)
            ->where('lon', '>=', $lon - $radius)
            ->where('lon', '<=', $lon + $radius)
            ->orderBy('forecast_time', 'asc')
            ->get();
        
        return $forecast;
    }
    
    /**
     * Pobierz najnowszą prognozę (ostatni run modelu)
     */
    public function getLatestForecast()
    {
        $latestRun = DB::table('gfs_forecast')
            ->max('run_time');
        
        $forecast = DB::table('gfs_forecast')
            ->where('run_time', $latestRun)
            ->orderBy('forecast_time', 'asc')
            ->get();
        
        return response()->json([
            'run_time' => $latestRun,
            'forecast_count' => $forecast->count(),
            'data' => $forecast
        ]);
    }
    
    /**
     * Pobierz aktualną pogodę dla danego miasta
     */
    public function getCurrentWeather(Request $request)
    {
        $lat = $request->input('lat', 52.23); // Domyślnie Warszawa
        $lon = $request->input('lon', 21.01);
        
        // Znajdujemy najbliższy punkt
        $weather = DB::table('gfs_forecast')
            ->selectRaw('*, 
                SQRT(POW(lat - ?, 2) + POW(lon - ?, 2)) as distance', 
                [$lat, $lon]
            )
            ->orderBy('distance', 'asc')
            ->orderBy('forecast_time', 'asc')
            ->first();
        
        if (!$weather) {
            return response()->json(['error' => 'Brak danych'], 404);
        }
        
        return response()->json([
            'location' => [
                'lat' => $weather->lat,
                'lon' => $weather->lon,
            ],
            'temperature' => round($weather->t2m, 1) . '°C',
            'feels_like' => round($weather->d2m, 1) . '°C',
            'humidity' => round($weather->rh, 0) . '%',
            'wind_speed' => round($weather->wind_speed, 1) . ' m/s',
            'wind_direction' => round($weather->wind_dir, 0) . '°',
            'pressure' => round($weather->mslp, 1) . ' hPa',
            'clouds' => round($weather->tcc, 0) . '%',
            'forecast_time' => $weather->forecast_time,
        ]);
    }
    
    /**
     * Pobierz prognozę godzinową na najbliższe 24h
     */
    public function get24HourForecast($lat, $lon)
    {
        $now = now();
        $tomorrow = now()->addHours(24);
        
        $forecast = DB::table('gfs_forecast')
            ->selectRaw('*, 
                SQRT(POW(lat - ?, 2) + POW(lon - ?, 2)) as distance', 
                [$lat, $lon]
            )
            ->whereBetween('forecast_time', [$now, $tomorrow])
            ->orderBy('distance', 'asc')
            ->orderBy('forecast_time', 'asc')
            ->limit(24)
            ->get();
        
        return response()->json($forecast);
    }
    
    /**
     * Sprawdź czy będzie padać w najbliższych godzinach
     */
    public function willItRain($lat, $lon, $hours = 6)
    {
        $endTime = now()->addHours($hours);
        
        $rain = DB::table('gfs_forecast')
            ->selectRaw('*, 
                SQRT(POW(lat - ?, 2) + POW(lon - ?, 2)) as distance', 
                [$lat, $lon]
            )
            ->where('forecast_time', '<=', $endTime)
            ->where('tp', '>', 0.5) // Opady > 0.5mm
            ->orderBy('distance', 'asc')
            ->orderBy('forecast_time', 'asc')
            ->get();
        
        return response()->json([
            'will_rain' => $rain->count() > 0,
            'rain_forecast' => $rain
        ]);
    }
    
    /**
     * Pobierz mapę temperatury (dla wizualizacji)
     */
    public function getTemperatureMap()
    {
        // Pobierz dane dla całego regionu
        $latestRun = DB::table('gfs_forecast')->max('run_time');
        
        $data = DB::table('gfs_forecast')
            ->select('lat', 'lon', 't2m', 'forecast_time')
            ->where('run_time', $latestRun)
            ->orderBy('forecast_time', 'asc')
            ->take(1000) // Ogranicz dla wydajności
            ->get();
        
        // Grupuj według czasu prognozy
        $grouped = $data->groupBy('forecast_time');
        
        return response()->json($grouped);
    }
    
    /**
     * Statystyki pogodowe
     */
    public function getWeatherStats($lat, $lon)
    {
        $radius = 0.25;
        
        $stats = DB::table('gfs_forecast')
            ->where('lat', '>=', $lat - $radius)
            ->where('lat', '<=', $lat + $radius)
            ->where('lon', '>=', $lon - $radius)
            ->where('lon', '<=', $lon + $radius)
            ->selectRaw('
                MIN(t2m) as min_temp,
                MAX(t2m) as max_temp,
                AVG(t2m) as avg_temp,
                MAX(wind_speed) as max_wind,
                SUM(tp) as total_rain,
                AVG(mslp) as avg_pressure
            ')
            ->first();
        
        return response()->json($stats);
    }
    
    /**
     * Ostrzeżenia pogodowe
     */
    public function getWeatherAlerts($lat, $lon)
    {
        $radius = 0.25;
        $alerts = [];
        
        // Sprawdź silny wiatr
        $strongWind = DB::table('gfs_forecast')
            ->where('lat', '>=', $lat - $radius)
            ->where('lat', '<=', $lat + $radius)
            ->where('lon', '>=', $lon - $radius)
            ->where('lon', '<=', $lon + $radius)
            ->where('wind_speed', '>', 15) // > 15 m/s
            ->exists();
        
        if ($strongWind) {
            $alerts[] = [
                'type' => 'wind',
                'severity' => 'warning',
                'message' => 'Silny wiatr przewidywany'
            ];
        }
        
        // Sprawdź intensywne opady
        $heavyRain = DB::table('gfs_forecast')
            ->where('lat', '>=', $lat - $radius)
            ->where('lat', '<=', $lat + $radius)
            ->where('lon', '>=', $lon - $radius)
            ->where('lon', '<=', $lon + $radius)
            ->where('tp', '>', 10) // > 10mm
            ->exists();
        
        if ($heavyRain) {
            $alerts[] = [
                'type' => 'rain',
                'severity' => 'warning',
                'message' => 'Intensywne opady przewidywane'
            ];
        }
        
        // Sprawdź potencjał burzowy (CAPE > 1000)
        $storms = DB::table('gfs_forecast')
            ->where('lat', '>=', $lat - $radius)
            ->where('lat', '<=', $lat + $radius)
            ->where('lon', '>=', $lon - $radius)
            ->where('lon', '<=', $lon + $radius)
            ->where('cape', '>', 1000)
            ->exists();
        
        if ($storms) {
            $alerts[] = [
                'type' => 'storm',
                'severity' => 'danger',
                'message' => 'Możliwe burze'
            ];
        }
        
        return response()->json([
            'has_alerts' => count($alerts) > 0,
            'alerts' => $alerts
        ]);
    }
}

/**
 * PRZYKŁADOWE ROUTES (routes/api.php):
 * 
 * Route::get('/weather/current', [WeatherController::class, 'getCurrentWeather']);
 * Route::get('/weather/forecast/{lat}/{lon}', [WeatherController::class, 'getForecastForLocation']);
 * Route::get('/weather/24h/{lat}/{lon}', [WeatherController::class, 'get24HourForecast']);
 * Route::get('/weather/rain/{lat}/{lon}', [WeatherController::class, 'willItRain']);
 * Route::get('/weather/map', [WeatherController::class, 'getTemperatureMap']);
 * Route::get('/weather/stats/{lat}/{lon}', [WeatherController::class, 'getWeatherStats']);
 * Route::get('/weather/alerts/{lat}/{lon}', [WeatherController::class, 'getWeatherAlerts']);
 */

/**
 * PRZYKŁADOWE UŻYCIE W BLADE:
 * 
 * // W kontrolerze:
 * public function index() {
 *     $weather = app(WeatherController::class)->getCurrentWeather(request());
 *     return view('weather', ['weather' => $weather]);
 * }
 * 
 * // W widoku (weather.blade.php):
 * <div class="weather-widget">
 *     <h2>Aktualna pogoda</h2>
 *     <p>Temperatura: {{ $weather['temperature'] }}</p>
 *     <p>Wiatr: {{ $weather['wind_speed'] }}</p>
 *     <p>Ciśnienie: {{ $weather['pressure'] }}</p>
 * </div>
 */
