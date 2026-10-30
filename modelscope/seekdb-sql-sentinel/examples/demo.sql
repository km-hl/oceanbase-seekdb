-- Offline sample only. Never execute directly against a production database.
SELECT * FROM orders
WHERE DATE(created_at) = '2026-10-30'
ORDER BY RAND()
LIMIT 20 OFFSET 5000;

UPDATE orders SET status = 'archived';

SELECT id FROM products WHERE product_name LIKE '%laptop%';
