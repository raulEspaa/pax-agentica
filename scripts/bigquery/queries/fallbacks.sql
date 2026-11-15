-- How often the AI fell back (a plan or letters asked for and never written: the last plan or
-- the bot stood in), timed out, or forfeited a year, per day over the last 30 days.
SELECT
  dt AS day,
  COUNT(*) AS decisions,
  ROUND(AVG(IF(fallback, 1, 0)), 3) AS fallback_rate,
  ROUND(AVG(IF(timed_out, 1, 0)), 3) AS timeout_rate,
  ROUND(AVG(IF(error IS NOT NULL, 1, 0)), 3) AS forfeit_rate,
  ROUND(AVG(IF(plan_asked AND NOT plan_written, 1, 0)), 3) AS plan_missed_rate,
  ROUND(AVG(IF(diplomacy_asked AND NOT diplomacy_written, 1, 0)), 3) AS letters_missed_rate
FROM pax_analytics.decisions
WHERE dt >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY day
ORDER BY day DESC;
