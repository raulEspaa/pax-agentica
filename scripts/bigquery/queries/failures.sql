-- Which failures the AI's model calls met over the last 30 days ("plan:TimeoutError",
-- "diplomacy:BudgetExceeded", ...), most common first. One per failed try, retries included.
SELECT
  failure,
  COUNT(*) AS tries,
  COUNT(DISTINCT CONCAT(table_id, ':', nation, ':', CAST(turn AS STRING))) AS decisions
FROM pax_analytics.decisions, UNNEST(failures) AS failure
WHERE dt >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY failure
ORDER BY tries DESC;
