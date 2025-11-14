-- ========================================
-- Kompletne utworzenie tabeli gfs_forecast
-- Zgodne z kolumnami zapisywanymi przez gfs_downloader_professional.py
-- ========================================

USE dane_gfs;

-- Usuń starą tabelę (UWAGA: To usunie wszystkie dane!)
DROP TABLE IF EXISTS gfs_forecast;

-- Utwórz nową tabelę z wszystkimi potrzebnymi kolumnami
CREATE TABLE gfs_forecast (
    -- Kolumny bazowe
    id INT AUTO_INCREMENT PRIMARY KEY,
    lat DOUBLE NOT NULL COMMENT 'Szerokość geograficzna (°N)',
    lon DOUBLE NOT NULL COMMENT 'Długość geograficzna (°E)',
    forecast_time DATETIME NOT NULL COMMENT 'Czas prognozy (dla jakiej daty/godziny jest prognoza)',
    run_time DATETIME NOT NULL COMMENT 'Czas uruchomienia modelu GFS (00, 06, 12, 18 UTC)',
    created_at DATETIME NOT NULL COMMENT 'Czas dodania rekordu do bazy',
    
    -- Parametry podstawowe (2m)
    t2m DOUBLE COMMENT 'Temperatura na wysokości 2m (°C)',
    d2m DOUBLE COMMENT 'Punkt rosy na wysokości 2m (°C)',
    rh DOUBLE COMMENT 'Wilgotność względna na wysokości 2m (%)',
    
    -- Wiatr 10m
    u10 DOUBLE COMMENT 'Składowa U wiatru na wysokości 10m (m/s)',
    v10 DOUBLE COMMENT 'Składowa V wiatru na wysokości 10m (m/s)',
    gust DOUBLE COMMENT 'Porywy wiatru (m/s)',
    
    -- Wiatr obliczone
    wind_speed DOUBLE COMMENT 'Prędkość wiatru obliczona z u10, v10 (m/s)',
    wind_dir DOUBLE COMMENT 'Kierunek wiatru w stopniach (0°=N, 90°=E, 180°=S, 270°=W)',
    
    -- Wiatr 80m
    u_wind80 DOUBLE COMMENT 'Składowa U wiatru na wysokości 80m (m/s)',
    v_wind80 DOUBLE COMMENT 'Składowa V wiatru na wysokości 80m (m/s)',
    t_wind80 DOUBLE COMMENT 'Temperatura na wysokości 80m (°C)',
    
    -- Ciśnienie i opady
    mslp DOUBLE COMMENT 'Ciśnienie na poziomie morza (hPa)',
    tp DOUBLE COMMENT 'Opady całkowite skumulowane od początku prognozy (mm) - może być NULL lub 0 dla początkowych godzin',
    prate DOUBLE COMMENT 'Intensywność opadów (kg/m²/s)',
    
    -- Zachmurzenie (wszystkie poziomy)
    tcc DOUBLE COMMENT 'Zachmurzenie całkowite (0-100%)',
    lcc DOUBLE COMMENT 'Zachmurzenie niskie (0-100%)',
    mcc DOUBLE COMMENT 'Zachmurzenie średnie (0-100%)',
    hcc DOUBLE COMMENT 'Zachmurzenie wysokie (0-100%)',
    
    -- Widzialność i promieniowanie
    vis DOUBLE COMMENT 'Widzialność (m)',
    dswrf DOUBLE COMMENT 'Promieniowanie słoneczne w dół (W/m²)',
    
    -- Parametry atmosferyczne
    cape DOUBLE COMMENT 'CAPE - Convective Available Potential Energy (J/kg)',
    cin DOUBLE COMMENT 'CIN - Convective Inhibition (J/kg)',
    pwat DOUBLE COMMENT 'Zawartość wody opadowej w całej kolumnie atmosferycznej (kg/m²)',
    
    -- Parametry wysokościowe 850 hPa
    t_t850 DOUBLE COMMENT 'Temperatura na poziomie 850 hPa (°C)',
    gh_t850 DOUBLE COMMENT 'Geopotencjał na poziomie 850 hPa (m)',
    
    -- Parametry wysokościowe 500 hPa
    gh_gh500 DOUBLE COMMENT 'Geopotencjał na poziomie 500 hPa (m)',
    
    -- Indeksy dla szybkiego wyszukiwania
    INDEX idx_location (lat, lon),
    INDEX idx_forecast_time (forecast_time),
    INDEX idx_run_time (run_time),
    INDEX idx_location_time (lat, lon, forecast_time, run_time),
    INDEX idx_forecast_run (forecast_time, run_time)
    
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Sprawdź strukturę tabeli
DESCRIBE gfs_forecast;

-- Pokaż wszystkie indeksy
SHOW INDEX FROM gfs_forecast;

-- Informacja:
-- Tabela jest gotowa! Możesz teraz uruchomić gfs_downloader_professional.py
-- który wypełni ją danymi.







