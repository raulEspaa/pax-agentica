-- Tables closed per day at the public server, why they closed, and how many had the AI.
WITH games AS (
  SELECT *
  FROM pax_analytics.games
  WHERE source = 'tables'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY table_id ORDER BY ended_at) = 1
)
SELECT
  dt AS day,
  COUNT(*) AS games,
  COUNTIF(closed_reason = 'over') AS played_to_the_end,
  COUNTIF(closed_reason = 'everyone left') AS left_early,
  COUNTIF(ARRAY_LENGTH(ai_nations) > 0) AS with_ai,
  ROUND(AVG(years_played), 1) AS avg_years,
  SUM(humans) AS human_crowns,
  ROUND(SUM(ai_cost_usd), 4) AS ai_usd
FROM games
GROUP BY day
ORDER BY day DESC;
