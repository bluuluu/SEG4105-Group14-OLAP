-- Adapted from the supplied Group 14 example queries.
-- Monthly net sales by region.
SELECT d.year, d.month, s.region, SUM(f.net_sales_amount) AS monthly_sales
FROM fact_sales f
JOIN dim_date d USING (date_key)
JOIN dim_store s USING (store_key)
GROUP BY d.year, d.month, s.region
ORDER BY d.year, d.month, s.region;

-- Products below their reorder point on the report's example date.
SELECT p.product_name, s.store_name, i.stock_on_hand, i.reorder_point
FROM fact_inventory_snapshot i
JOIN dim_product p USING (product_key)
JOIN dim_store s USING (store_key)
JOIN dim_date d USING (date_key)
WHERE d.full_date = DATE '2026-11-01'
  AND i.stock_on_hand < i.reorder_point
ORDER BY i.reorder_point - i.stock_on_hand DESC, p.product_name, s.store_name;

-- Inventory grain validation. Expect zero rows.
SELECT date_key, store_key, product_key, COUNT(*) AS duplicate_count
FROM fact_inventory_snapshot
GROUP BY date_key, store_key, product_key
HAVING COUNT(*) > 1;
