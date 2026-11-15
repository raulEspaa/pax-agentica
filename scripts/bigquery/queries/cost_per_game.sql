-- What the AI cost per game at the public tables, newest first. A table closes once, but two
-- revisions overlapping in a deploy could both report it: keep the first row of each table.
SELECT
  table_id,
  DATE(ended_at) AS day,
  closed_reason,
  years_played,
  humans,
  ARRAY_LENGTH(ai_nations) AS ai_crowns,
  ai_cost_usd,
  SAFE_DIVIDE(ai_cost_usd, years_played * ARRAY_LENGTH(ai_nations)) AS usd_per_ai_year
FROM pax_analytics.games
WHERE source = 'tables' AND ARRAY_LENGTH(ai_nations) > 0
QUALIFY ROW_NUMBER() OVER (PARTITION BY table_id ORDER BY ended_at) = 1
ORDER BY ended_at DESC
LIMIT 100;
