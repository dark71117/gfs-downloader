-- ========================================
-- Przykładowe zapytania pomocnicze
-- Do pobierania danych dla miasta
-- ========================================

USE dane_gfs;

-- ========================================
-- 1. Pobierz najnowsze dane dla miasta (lat, lon)
-- Zwraca tylko dane z najnowszego run_time
-- Jeśli są dane z 06:00 i 12:00, zwraca tylko 12:00
-- ========================================

-- Przykład: Warszawa (około lat=52.23, lon=21.01)
-- Zastąp wartości dla swojego miasta

SELECT *
FROM gfs_forecast
WHERE lat = 52.23 AND lon = 21.01
AND run_time = (SELECT MAX(run_time) FROM gfs_forecast)
ORDER BY forecast_time ASC;

-- ========================================
-- 2. Pobierz najnowsze dane dla miasta dla konkretnego forecast_time
-- ========================================

SELECT *
FROM gfs_forecast
WHERE lat = 52.23 AND lon = 21.01
AND forecast_time = '2025-11-03 12:00:00'
AND run_time = (
    SELECT MAX(run_time) 
    FROM gfs_forecast 
    WHERE forecast_time = '2025-11-03 12:00:00'
)
LIMIT 1;

-- ========================================
-- 3. Pobierz najnowsze prognozy dla miasta (bez duplikatów)
-- Zwraca tylko najnowsze run_time dla każdego forecast_time
-- ========================================

SELECT f1.*
FROM gfs_forecast f1
INNER JOIN (
    SELECT forecast_time, MAX(run_time) as max_run_time
    FROM gfs_forecast
    WHERE lat = 52.23 AND lon = 21.01
    GROUP BY forecast_time
) f2 ON f1.forecast_time = f2.forecast_time 
    AND f1.run_time = f2.max_run_time
WHERE f1.lat = 52.23 AND f1.lon = 21.01
ORDER BY f1.forecast_time ASC;

-- ========================================
-- 4. Pobierz dostępne forecast_time dla miasta z najnowszego run
-- ========================================

SELECT DISTINCT forecast_time 
FROM gfs_forecast
WHERE lat = 52.23 AND lon = 21.01
AND run_time = (SELECT MAX(run_time) FROM gfs_forecast)
ORDER BY forecast_time ASC;

-- ========================================
-- 5. Pobierz najnowszą prognozę dla miasta
-- Zwraca prognozę z najnowszym run_time i najnowszym forecast_time
-- ========================================

SELECT *
FROM gfs_forecast
WHERE lat = 52.23 AND lon = 21.01
AND run_time = (SELECT MAX(run_time) FROM gfs_forecast)
AND forecast_time = (
    SELECT MAX(forecast_time) 
    FROM gfs_forecast 
    WHERE lat = 52.23 
    AND lon = 21.01 
    AND run_time = (SELECT MAX(run_time) FROM gfs_forecast)
)
LIMIT 1;

-- ========================================
-- 6. Pobierz opady (tp) dla miasta - tylko nie-null i nie-zero wartości
-- ========================================

SELECT forecast_time, tp, run_time
FROM gfs_forecast
WHERE lat = 52.23 AND lon = 21.01
AND run_time = (SELECT MAX(run_time) FROM gfs_forecast)
AND tp IS NOT NULL
AND tp > 0
ORDER BY forecast_time ASC;

-- ========================================
-- 7. Sprawdź ile rekordów jest dla miasta z najnowszego run
-- ========================================

SELECT 
    COUNT(*) as total_records,
    COUNT(DISTINCT forecast_time) as unique_forecast_times,
    MIN(forecast_time) as first_forecast,
    MAX(forecast_time) as last_forecast,
    MAX(run_time) as run_time
FROM gfs_forecast
WHERE lat = 52.23 AND lon = 21.01
AND run_time = (SELECT MAX(run_time) FROM gfs_forecast);

-- ========================================
-- 8. Przykłady dla różnych miast
-- ========================================

-- Warszawa: lat=52.23, lon=21.01
-- Kraków: lat=50.06, lon=19.94
-- Gdańsk: lat=54.35, lon=18.65
-- Wrocław: lat=51.11, lon=17.03
-- Poznań: lat=52.41, lon=16.93

-- Przykład dla Krakowa:
/*
SELECT *
FROM gfs_forecast
WHERE lat BETWEEN 50.0 AND 50.1 AND lon BETWEEN 19.9 AND 20.0
AND run_time = (SELECT MAX(run_time) FROM gfs_forecast)
ORDER BY forecast_time ASC;
*/







