-- ========================================
-- Skrypt SQL do utworzenia bazy danych GFS
-- ========================================

-- 1. Tworzenie bazy danych (jeśli nie istnieje)
CREATE DATABASE IF NOT EXISTS dane_gfs 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

-- 2. Używamy bazy danych
USE dane_gfs;

-- 3. Tworzenie tabeli gfs_forecast
-- Tabela zostanie automatycznie utworzona przez skrypt Python,
-- ale możesz ją utworzyć ręcznie:

DROP TABLE IF EXISTS gfs_forecast;

CREATE TABLE gfs_forecast (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lat DOUBLE NOT NULL,
    lon DOUBLE NOT NULL,
    forecast_time DATETIME NOT NULL,
    run_time DATETIME NOT NULL,
    created_at DATETIME NOT NULL,
    
    -- Parametry podstawowe
    t2m DOUBLE COMMENT 'Temperatura 2m (°C)',
    d2m DOUBLE COMMENT 'Punkt rosy 2m (°C)',
    rh DOUBLE COMMENT 'Wilgotność względna (%)',
    
    -- Wiatr
    u10 DOUBLE COMMENT 'Składowa U wiatru 10m (m/s)',
    v10 DOUBLE COMMENT 'Składowa V wiatru 10m (m/s)',
    wind_speed DOUBLE COMMENT 'Prędkość wiatru (m/s)',
    wind_dir DOUBLE COMMENT 'Kierunek wiatru (°)',
    gust DOUBLE COMMENT 'Porywy wiatru (m/s)',
    
    -- Ciśnienie i opady
    mslp DOUBLE COMMENT 'Ciśnienie na poziomie morza (hPa)',
    tp DOUBLE COMMENT 'Opady całkowite (mm)',
    prate DOUBLE COMMENT 'Intensywność opadów (kg/m²/s)',
    
    -- Zachmurzenie
    tcc DOUBLE COMMENT 'Zachmurzenie całkowite (%)',
    lcc DOUBLE COMMENT 'Zachmurzenie niskie (%)',
    mcc DOUBLE COMMENT 'Zachmurzenie średnie (%)',
    hcc DOUBLE COMMENT 'Zachmurzenie wysokie (%)',
    
    -- Inne
    vis DOUBLE COMMENT 'Widzialność (m)',
    dswrf DOUBLE COMMENT 'Promieniowanie słoneczne (W/m²)',
    pwat DOUBLE COMMENT 'Woda opadowa (kg/m²)',
    
    -- Parametry wysokościowe
    t850 DOUBLE COMMENT 'Temperatura 850 hPa (K)',
    gh500 DOUBLE COMMENT 'Geopotencjał 500 hPa (m)',
    cape DOUBLE COMMENT 'CAPE (J/kg)',
    cin DOUBLE COMMENT 'CIN (J/kg)',
    
    -- Indeksy
    INDEX idx_location (lat, lon),
    INDEX idx_time (forecast_time),
    INDEX idx_run (run_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Sprawdzenie struktury tabeli
DESCRIBE gfs_forecast;

-- 5. Przykładowe zapytanie po załadowaniu danych
-- SELECT * FROM gfs_forecast 
-- WHERE lat BETWEEN 50 AND 52 
-- AND lon BETWEEN 19 AND 21 
-- ORDER BY forecast_time 
-- LIMIT 10;
