-- Cost and latency of the AI council's decisions, per day and model, over the last 30 days.
-- Latency runs from starting to think to the orders; the humans' year hides most of it.
SELECT
  dt AS day,
  model,
  COUNT(*) AS decisions,
  SUM(model_calls) AS model_calls,
  ROUND(SUM(cost_usd), 4) AS usd,
  ROUND(AVG(cost_usd), 6) AS usd_per_decision,
  ROUND(SAFE_DIVIDE(SUM(cost_usd), COUNTIF(plan_written)), 6) AS usd_per_plan_written,
  APPROX_QUANTILES(latency_s, 100)[OFFSET(50)] AS latency_p50_s,
  APPROX_QUANTILES(latency_s, 100)[OFFSET(95)] AS latency_p95_s
FROM pax_analytics.decisions
WHERE dt >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY day, model
ORDER BY day DESC, model;
