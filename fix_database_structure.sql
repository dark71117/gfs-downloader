-- ========================================
-- Poprawiona struktura tabeli gfs_forecast
-- Zgodna z kolumnami zapisywanymi przez gfs_downloader_professional.py
-- ========================================

USE dane_gfs;

-- Sprawdź jakie kolumny są faktycznie zapisywane:
-- Z kodu Python:
-- prmsl (NIE mslp!), tp, tcc, t2m, d2m, r2 (NIE rh!), u10, v10, gust,
-- u_wind80, v_wind80, t_wind80, cape, cin, pwat, t_t850, gh_t850, gh_gh500,
-- wind_speed, wind_dir (obliczone)

-- 1. Usuń nieistniejące kolumny (jeśli istnieją)
-- 2. Dodaj brakujące kolumny (jeśli ich nie ma)
-- 3. Dodaj komentarze
-- 4. Dodaj indeksy

-- Dodaj kolumny które mogą brakować (jeśli nie istnieją)
-- MySQL nie obsługuje IF NOT EXISTS dla kolumn, więc używamy procedury sprawdzającej

-- Sprawdź i dodaj komentarze tylko dla istniejących kolumn
-- Użyj ręcznie w phpMyAdmin lub sprawdź najpierw które kolumny istnieją

-- UWAGA: Uruchom każdy MODIFY COLUMN osobno lub sprawdź najpierw które kolumny istnieją!

-- Najpierw sprawdź strukturę tabeli:
-- DESCRIBE gfs_forecast;

-- Następnie uruchom tylko te MODIFY COLUMN dla kolumn które istnieją:

-- Kolumny bazowe
ALTER TABLE gfs_forecast MODIFY COLUMN lat DOUBLE NOT NULL COMMENT 'Szerokość geograficzna (°N)';
ALTER TABLE gfs_forecast MODIFY COLUMN lon DOUBLE NOT NULL COMMENT 'Długość geograficzna (°E)';
ALTER TABLE gfs_forecast MODIFY COLUMN forecast_time DATETIME NOT NULL COMMENT 'Czas prognozy (dla jakiej daty/godziny jest prognoza)';
ALTER TABLE gfs_forecast MODIFY COLUMN run_time DATETIME NOT NULL COMMENT 'Czas uruchomienia modelu GFS (00, 06, 12, 18 UTC)';
ALTER TABLE gfs_forecast MODIFY COLUMN created_at DATETIME NOT NULL COMMENT 'Czas dodania rekordu do bazy';

-- Parametry podstawowe (jeśli istnieją)
ALTER TABLE gfs_forecast MODIFY COLUMN t2m DOUBLE COMMENT 'Temperatura na wysokości 2m (°C)';
ALTER TABLE gfs_forecast MODIFY COLUMN d2m DOUBLE COMMENT 'Punkt rosy na wysokości 2m (°C)';
ALTER TABLE gfs_forecast MODIFY COLUMN rh DOUBLE COMMENT 'Wilgotność względna na wysokości 2m (%)';
-- Uwaga: Kod zapisuje r2, ale w bazie może być rh - sprawdź!

-- Wiatr 10m (jeśli istnieją)
ALTER TABLE gfs_forecast MODIFY COLUMN u10 DOUBLE COMMENT 'Składowa U wiatru na wysokości 10m (m/s)';
ALTER TABLE gfs_forecast MODIFY COLUMN v10 DOUBLE COMMENT 'Składowa V wiatru na wysokości 10m (m/s)';
ALTER TABLE gfs_forecast MODIFY COLUMN gust DOUBLE COMMENT 'Porywy wiatru (m/s)';

-- Wiatr 80m (jeśli istnieją)
ALTER TABLE gfs_forecast MODIFY COLUMN u_wind80 DOUBLE COMMENT 'Składowa U wiatru na wysokości 80m (m/s)';
ALTER TABLE gfs_forecast MODIFY COLUMN v_wind80 DOUBLE COMMENT 'Składowa V wiatru na wysokości 80m (m/s)';
ALTER TABLE gfs_forecast MODIFY COLUMN t_wind80 DOUBLE COMMENT 'Temperatura na wysokości 80m (°C)';

-- Wiatr obliczone (jeśli istnieją)
ALTER TABLE gfs_forecast MODIFY COLUMN wind_speed DOUBLE COMMENT 'Prędkość wiatru obliczona z u10, v10 (m/s)';
ALTER TABLE gfs_forecast MODIFY COLUMN wind_dir DOUBLE COMMENT 'Kierunek wiatru w stopniach (0°=N, 90°=E, 180°=S, 270°=W)';

-- Ciśnienie i opady (jeśli istnieją)
ALTER TABLE gfs_forecast MODIFY COLUMN mslp DOUBLE COMMENT 'Ciśnienie na poziomie morza (hPa)';
ALTER TABLE gfs_forecast MODIFY COLUMN tp DOUBLE COMMENT 'Opady całkowite skumulowane od początku prognozy (mm) - może być NULL lub 0 dla początkowych godzin';
ALTER TABLE gfs_forecast MODIFY COLUMN prate DOUBLE COMMENT 'Intensywność opadów (kg/m²/s)';

-- Zachmurzenie (jeśli istnieją)
ALTER TABLE gfs_forecast MODIFY COLUMN tcc DOUBLE COMMENT 'Zachmurzenie całkowite (0-100%)';
ALTER TABLE gfs_forecast MODIFY COLUMN lcc DOUBLE COMMENT 'Zachmurzenie niskie (0-100%)';
ALTER TABLE gfs_forecast MODIFY COLUMN mcc DOUBLE COMMENT 'Zachmurzenie średnie (0-100%)';
ALTER TABLE gfs_forecast MODIFY COLUMN hcc DOUBLE COMMENT 'Zachmurzenie wysokie (0-100%)';

-- Parametry atmosferyczne (jeśli istnieją)
ALTER TABLE gfs_forecast MODIFY COLUMN cape DOUBLE COMMENT 'CAPE - Convective Available Potential Energy (J/kg)';
ALTER TABLE gfs_forecast MODIFY COLUMN cin DOUBLE COMMENT 'CIN - Convective Inhibition (J/kg)';
ALTER TABLE gfs_forecast MODIFY COLUMN pwat DOUBLE COMMENT 'Zawartość wody opadowej w całej kolumnie atmosferycznej (kg/m²)';

-- Parametry wysokościowe 850 hPa (jeśli istnieją)
ALTER TABLE gfs_forecast MODIFY COLUMN t_t850 DOUBLE COMMENT 'Temperatura na poziomie 850 hPa (°C)';
ALTER TABLE gfs_forecast MODIFY COLUMN gh_t850 DOUBLE COMMENT 'Geopotencjał na poziomie 850 hPa (m)';

-- Parametry wysokościowe 500 hPa (jeśli istnieje)
ALTER TABLE gfs_forecast MODIFY COLUMN gh_gh500 DOUBLE COMMENT 'Geopotencjał na poziomie 500 hPa (m)';

-- Widzialność i promieniowanie (jeśli istnieją)
ALTER TABLE gfs_forecast MODIFY COLUMN vis DOUBLE COMMENT 'Widzialność (m)';
ALTER TABLE gfs_forecast MODIFY COLUMN dswrf DOUBLE COMMENT 'Promieniowanie słoneczne w dół (W/m²)';

-- UWAGA: Kod zapisuje parametry z następującymi nazwami:
-- prmsl -> mslp (ciśnienie)
-- r2 -> rh (wilgotność względna)
-- prate, lcc, mcc, hcc, vis, dswrf są zapisywane bez zmian

-- Usuń kolumny których nie ma w kodzie Python (jeśli istnieją)
-- UWAGA: Uruchom tylko jeśli masz pewność że te kolumny istnieją i nie są używane!

/*
ALTER TABLE gfs_forecast
    DROP COLUMN IF EXISTS mslp,  -- Używamy prmsl
    DROP COLUMN IF EXISTS rh,     -- Używamy r2
    DROP COLUMN IF EXISTS lcc,    -- Nie jest pobierane
    DROP COLUMN IF EXISTS mcc,    -- Nie jest pobierane
    DROP COLUMN IF EXISTS hcc,    -- Nie jest pobierane
    DROP COLUMN IF EXISTS vis,    -- Nie jest pobierane
    DROP COLUMN IF EXISTS dswrf,  -- Nie jest pobierane
    DROP COLUMN IF EXISTS prate,  -- Nie jest pobierane
    DROP COLUMN IF EXISTS t850,   -- Używamy t_t850
    DROP COLUMN IF EXISTS gh500;  -- Używamy gh_gh500
*/

-- Dodaj indeksy (jeśli nie istnieją)
CREATE INDEX IF NOT EXISTS idx_location_composite ON gfs_forecast(lat, lon);
CREATE INDEX IF NOT EXISTS idx_location_time ON gfs_forecast(lat, lon, forecast_time, run_time);
CREATE INDEX IF NOT EXISTS idx_forecast_run ON gfs_forecast(forecast_time, run_time);
CREATE INDEX IF NOT EXISTS idx_run_time ON gfs_forecast(run_time);
CREATE INDEX IF NOT EXISTS idx_forecast_time ON gfs_forecast(forecast_time);

-- Sprawdź strukturę tabeli
DESCRIBE gfs_forecast;

-- Pokaż wszystkie indeksy
SHOW INDEX FROM gfs_forecast;

