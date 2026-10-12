"""Parameterized BigQuery SQL templates for FinCity's production graph backend.

Replace ``project.dataset`` with the deployment's configured BigQuery location.
Values are query parameters; table identifiers must be configured and quoted by
the application, never supplied as request parameters.
"""

# ============================================================
# 1. WINDOWED ACCOUNT ADJACENCY
# ============================================================
ACCOUNT_ADJACENCY_QUERY = """
SELECT
  nameOrig AS source,
  nameDest AS target,
  COUNT(*) AS txn_count,
  SUM(amount) AS total_amount,
  AVG(amount) AS avg_amount,
  COUNTIF(isFraud = 1) AS fraud_count,
  MIN(step) AS first_step,
  MAX(step) AS last_step
FROM `project.dataset.transactions`
WHERE step BETWEEN @window_start AND @window_end
GROUP BY source, target
HAVING COUNT(*) >= @min_txn_count
"""

# ============================================================
# 2. ACCOUNT METRICS
# ============================================================
NODE_METRICS_QUERY = """
WITH windowed AS (
  SELECT *
  FROM `project.dataset.transactions`
  WHERE step BETWEEN @window_start AND @window_end
),
balance_events AS (
  SELECT
    nameOrig AS account_id,
    step,
    newbalanceOrig AS latest_balance
  FROM windowed
  UNION ALL
  SELECT
    nameDest AS account_id,
    step,
    newbalanceDest AS latest_balance
  FROM windowed
),
outgoing AS (
  SELECT
    nameOrig AS account_id,
    COUNT(*) AS outgoing_txns,
    SUM(amount) AS outgoing_amount,
    COUNTIF(isFraud = 1) AS outgoing_fraud
  FROM windowed
  GROUP BY account_id
),
incoming AS (
  SELECT
    nameDest AS account_id,
    COUNT(*) AS incoming_txns,
    SUM(amount) AS incoming_amount,
    COUNTIF(isFraud = 1) AS incoming_fraud
  FROM windowed
  GROUP BY account_id
),
balances AS (
  SELECT account_id, latest_balance
  FROM balance_events
  QUALIFY ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY step DESC) = 1
),
accounts AS (
  SELECT account_id FROM outgoing
  UNION DISTINCT
  SELECT account_id FROM incoming
)
SELECT
  a.account_id,
  CASE
    WHEN STARTS_WITH(a.account_id, 'C') THEN 'customer'
    WHEN STARTS_WITH(a.account_id, 'M') THEN 'merchant'
    ELSE 'unknown'
  END AS account_type,
  COALESCE(o.outgoing_txns, 0) AS outgoing_txns,
  COALESCE(i.incoming_txns, 0) AS incoming_txns,
  COALESCE(o.outgoing_amount, 0) AS outgoing_amount,
  COALESCE(i.incoming_amount, 0) AS incoming_amount,
  COALESCE(o.outgoing_fraud, 0) AS outgoing_fraud,
  COALESCE(i.incoming_fraud, 0) AS incoming_fraud,
  COALESCE(b.latest_balance, 0) AS latest_balance,
  SAFE_DIVIDE(
    COALESCE(o.outgoing_fraud, 0) + COALESCE(i.incoming_fraud, 0),
    GREATEST(1, COALESCE(o.outgoing_txns, 0) + COALESCE(i.incoming_txns, 0))
  ) AS risk_score
FROM accounts a
LEFT JOIN outgoing o USING (account_id)
LEFT JOIN incoming i USING (account_id)
LEFT JOIN balances b USING (account_id)
"""

# ============================================================
# 3. RING METRICS (connected components are precomputed offline)
# ============================================================
FRAUD_RING_QUERY = """
WITH internal_edges AS (
  SELECT
    source.component_id AS ring_id,
    a.source,
    a.target,
    a.txn_count,
    a.fraud_count
  FROM `project.dataset.account_adjacency` a
  JOIN `project.dataset.account_components` source
    ON source.account_id = a.source
  JOIN `project.dataset.account_components` target
    ON target.account_id = a.target
   AND target.component_id = source.component_id
),
edge_metrics AS (
  SELECT
    ring_id,
    COUNT(*) AS internal_edges,
    SUM(fraud_count) AS total_fraud_txns,
    SUM(txn_count) AS total_txns,
    SAFE_DIVIDE(SUM(fraud_count), SUM(txn_count)) AS fraud_rate
  FROM internal_edges
  GROUP BY ring_id
),
member_metrics AS (
  SELECT
    c.component_id AS ring_id,
    COUNT(DISTINCT c.account_id) AS ring_size,
    AVG(m.risk_score) AS avg_risk_score,
    COUNTIF(m.account_type = 'customer') AS customer_count,
    COUNTIF(m.account_type = 'merchant') AS merchant_count
  FROM `project.dataset.account_components` c
  JOIN `project.dataset.account_metrics` m USING (account_id)
  GROUP BY ring_id
)
SELECT
  members.*,
  edges.internal_edges,
  edges.total_fraud_txns,
  edges.total_txns,
  edges.fraud_rate
FROM member_metrics members
JOIN edge_metrics edges USING (ring_id)
WHERE edges.fraud_rate >= @min_fraud_rate OR edges.total_fraud_txns > 0
ORDER BY edges.fraud_rate DESC, members.ring_size DESC
"""

# ============================================================
# 4. TEMPORAL RING METRICS
# ============================================================
TEMPORAL_EVOLUTION_QUERY = """
WITH daily_adjacency AS (
  SELECT
    step AS day,
    nameOrig AS source,
    nameDest AS target,
    COUNT(*) AS txn_count,
    COUNTIF(isFraud = 1) AS fraud_count
  FROM `project.dataset.transactions`
  GROUP BY day, source, target
),
daily_internal_edges AS (
  SELECT
    components.day,
    components.component_id AS ring_id,
    components.account_id,
    adjacency.target,
    adjacency.txn_count,
    adjacency.fraud_count
  FROM `project.dataset.daily_components` components
  JOIN daily_adjacency adjacency
    ON adjacency.day = components.day
   AND adjacency.source = components.account_id
  JOIN `project.dataset.daily_components` target
    ON target.day = components.day
   AND target.component_id = components.component_id
   AND target.account_id = adjacency.target
),
ring_metrics AS (
  SELECT
    day,
    ring_id,
    COUNT(DISTINCT account_id) AS ring_size,
    SUM(fraud_count) AS fraud_txns,
    SUM(txn_count) AS total_txns,
    SAFE_DIVIDE(SUM(fraud_count), SUM(txn_count)) AS fraud_rate
  FROM daily_internal_edges
  GROUP BY day, ring_id
)
SELECT *
FROM ring_metrics
WHERE fraud_rate >= @min_fraud_rate OR fraud_txns > 0
ORDER BY day, fraud_rate DESC
"""

# ============================================================
# 5. CASE FILE
# ============================================================
CASE_FILE_QUERY = """
SELECT
  m.account_id,
  m.account_type,
  m.latest_balance,
  m.outgoing_txns,
  m.incoming_txns,
  m.outgoing_fraud,
  m.incoming_fraud,
  m.risk_score,
  ARRAY(
    SELECT AS STRUCT step, type, amount, nameDest, isFraud
    FROM `project.dataset.transactions`
    WHERE nameOrig = @account_id
    ORDER BY step DESC
    LIMIT 20
  ) AS recent_outgoing,
  ARRAY(
    SELECT AS STRUCT step, type, amount, nameOrig, isFraud
    FROM `project.dataset.transactions`
    WHERE nameDest = @account_id
    ORDER BY step DESC
    LIMIT 20
  ) AS recent_incoming,
  ARRAY(
    SELECT DISTINCT component_id
    FROM `project.dataset.account_components`
    WHERE account_id = @account_id
  ) AS fraud_rings
FROM `project.dataset.account_metrics` m
WHERE m.account_id = @account_id
"""

# ============================================================
# 6. HIGHEST-VALUE FRAUD TRANSACTION IN A RING
# ============================================================
WORST_TXN_IN_RING_QUERY = """
SELECT
  step,
  type,
  amount,
  nameOrig,
  nameDest,
  isFraud,
  origin.risk_score AS orig_risk,
  destination.risk_score AS dest_risk
FROM `project.dataset.transactions`
JOIN `project.dataset.account_metrics` origin
  ON nameOrig = origin.account_id
JOIN `project.dataset.account_metrics` destination
  ON nameDest = destination.account_id
WHERE nameOrig IN UNNEST(@ring_nodes)
  AND nameDest IN UNNEST(@ring_nodes)
  AND isFraud = 1
ORDER BY amount DESC
LIMIT 1
"""
