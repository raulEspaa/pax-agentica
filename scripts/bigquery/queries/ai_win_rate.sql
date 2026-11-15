-- How often each kind of ruler wins a finished game, and its average standing: the AI council
-- against the bots (and the humans). Every crown of every finished game counts once. Few games
-- make a noisy rate: read `crowns` before `win_rate` (9 crowns a game, so a fair share is 0.11).
WITH games AS (
  SELECT *
  FROM pax_analytics.games
  WHERE finished
  QUALIFY ROW_NUMBER() OVER (PARTITION BY source, table_id ORDER BY ended_at) = 1
)
SELECT
  g.source,
  s.ruler,
  COUNT(*) AS crowns,
  COUNTIF(s.nation = g.winner) AS wins,
  ROUND(SAFE_DIVIDE(COUNTIF(s.nation = g.winner), COUNT(*)), 3) AS win_rate,
  ROUND(AVG(s.standing), 1) AS avg_standing,
  ROUND(AVG(IF(s.alive, 1, 0)), 3) AS survival
FROM games AS g, UNNEST(g.standings) AS s
GROUP BY g.source, s.ruler
ORDER BY g.source, win_rate DESC;
