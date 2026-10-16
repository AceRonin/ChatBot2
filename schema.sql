CREATE DATABASE IF NOT EXISTS product_scout
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE product_scout;

CREATE TABLE IF NOT EXISTS products (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(160) NOT NULL,
  brand VARCHAR(100) NOT NULL,
  category VARCHAR(100) NOT NULL,
  description TEXT NOT NULL,
  price DECIMAL(10, 2) NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'USD',
  key_features JSON NOT NULL,
  battery_life_hours DECIMAL(5, 1) NULL,
  noise_cancelling BOOLEAN NOT NULL DEFAULT FALSE,
  weight_grams DECIMAL(6, 1) NULL,
  warranty_years DECIMAL(3, 1) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_products_brand_name (brand, name),
  INDEX idx_products_category_brand (category, brand)
) ENGINE=InnoDB;

INSERT INTO products
  (name, brand, category, description, price, currency, key_features,
   battery_life_hours, noise_cancelling, weight_grams, warranty_years)
VALUES
  ('QuietComfort Ultra Headphones', 'Bose', 'Wireless headphones',
   'Premium over-ear headphones with immersive spatial audio and adjustable noise cancelling.',
   429.00, 'USD', JSON_ARRAY('Immersive spatial audio', 'Adjustable ANC', 'Bluetooth multipoint'),
   24, TRUE, 250, 1),
  ('WH-1000XM5', 'Sony', 'Wireless headphones',
   'Lightweight over-ear headphones with adaptive noise cancelling and hands-free voice control.',
   399.99, 'USD', JSON_ARRAY('Adaptive ANC', 'Speak-to-Chat', 'Multipoint connection'),
   30, TRUE, 250, 1),
  ('Momentum 4 Wireless', 'Sennheiser', 'Wireless headphones',
   'Over-ear headphones designed for long listening sessions, with adaptive noise cancellation.',
   349.95, 'USD', JSON_ARRAY('Adaptive ANC', 'Customizable sound', 'Foldable design'),
   60, TRUE, 293, 2),
  ('Tune 760NC', 'JBL', 'Wireless headphones',
   'Foldable wireless headphones with active noise cancelling and a compact travel-friendly design.',
   129.95, 'USD', JSON_ARRAY('Active noise cancelling', 'Foldable design', 'Voice assistant support'),
   50, TRUE, 220, 1)
ON DUPLICATE KEY UPDATE
  description = VALUES(description),
  price = VALUES(price),
  currency = VALUES(currency),
  key_features = VALUES(key_features),
  battery_life_hours = VALUES(battery_life_hours),
  noise_cancelling = VALUES(noise_cancelling),
  weight_grams = VALUES(weight_grams),
  warranty_years = VALUES(warranty_years);
