-- genre_master
DROP TABLE IF EXISTS genre_master;
CREATE TABLE genre_master (
    code TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- images
DROP TABLE IF EXISTS images;
CREATE TABLE images (
    id TEXT PRIMARY KEY NOT NULL,
    "order" INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- large_service_area_master
DROP TABLE IF EXISTS large_service_area_master;
CREATE TABLE large_service_area_master (
    code TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- service_area_master
DROP TABLE IF EXISTS service_area_master;
CREATE TABLE service_area_master (
    code TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    large_service_area_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (large_service_area_code) REFERENCES large_service_area_master(code)
);

-- large_area_master
DROP TABLE IF EXISTS large_area_master;
CREATE TABLE large_area_master (
    code TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    service_area_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (service_area_code) REFERENCES service_area_master(code)
);

-- middle_area_master
DROP TABLE IF EXISTS middle_area_master;
CREATE TABLE middle_area_master (
    code TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    large_area_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (large_area_code) REFERENCES large_area_master(code)
);

-- small_area_code
DROP TABLE IF EXISTS small_area_master;
CREATE TABLE small_area_master (
    code TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    middle_area_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (middle_area_code) REFERENCES middle_area_master(code)
);

-- restaurants
DROP TABLE IF EXISTS restaurants;
CREATE TABLE restaurants (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    small_area_code TEXT NOT NULL,
    genre_code TEXT NOT NULL,
    sub_genre_code TEXT NOT NULL,
    address TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    open_hours TEXT,
    close_days TEXT,
    parking TEXT,
    is_notified INTEGER DEFAULT 0 NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (small_area_code) REFERENCES small_area_master(code),
    FOREIGN KEY (genre_code) REFERENCES genre_master(code),
    FOREIGN KEY (sub_genre_code) REFERENCES genre_master(code)
);

-- restaurants_tmp
DROP TABLE IF EXISTS restaurants_tmp;
CREATE TABLE restaurants_tmp (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT,
    small_area_code TEXT,
    genre_code TEXT,
    sub_genre_code TEXT,
    address TEXT,
    latitude REAL,
    longitude REAL,
    open_hours TEXT,
    close_days TEXT,
    parking TEXT,
    FOREIGN KEY (small_area_code) REFERENCES small_area_master(code),
    FOREIGN KEY (genre_code) REFERENCES genre_master(code),
    FOREIGN KEY (sub_genre_code) REFERENCES genre_master(code)
);