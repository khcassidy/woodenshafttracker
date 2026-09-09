-- Initial schema. Single source of truth, applied via PRAGMA user_version.
-- Integer minor units throughout: spine in centipounds (cp), weight in
-- centigrams (cg), two-reading average spine in millipounds (mlb).
-- Every column that carries a unit says so in its name.

CREATE TABLE app_meta (
  key        TEXT PRIMARY KEY,
  int_value  INTEGER,
  text_value TEXT
);
INSERT INTO app_meta(key, int_value) VALUES ('pool_version', 0);

-- 2.2 Ordered lookup lists. sort_order is NOT unique: reordering rewrites
-- 1..n in one transaction via PUT /api/lookups/{kind}/order. Never sort a
-- pull-down alphabetically -- that is the explicit requirement this column
-- exists for.

CREATE TABLE diameter_option (
  id            INTEGER PRIMARY KEY,
  label         TEXT    NOT NULL UNIQUE,
  sixty_fourths INTEGER UNIQUE,                   -- NULL only for the UNKNOWN sentinel
  sort_order    INTEGER NOT NULL,
  is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active  IN (0,1)),
  is_unknown    INTEGER NOT NULL DEFAULT 0 CHECK (is_unknown IN (0,1)),
  created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (id <> 0 OR is_unknown = 1),
  CHECK (is_unknown = 0 OR sixty_fourths IS NULL)
);
CREATE INDEX        ix_diameter_sort    ON diameter_option(sort_order);
CREATE UNIQUE INDEX ux_diameter_unknown ON diameter_option(is_unknown) WHERE is_unknown = 1;

CREATE TABLE wood_option (
  id         INTEGER PRIMARY KEY,
  label      TEXT    NOT NULL UNIQUE,
  sort_order INTEGER NOT NULL,
  is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active  IN (0,1)),
  is_unknown INTEGER NOT NULL DEFAULT 0 CHECK (is_unknown IN (0,1)),
  created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (id <> 0 OR is_unknown = 1)
);
CREATE INDEX        ix_wood_sort    ON wood_option(sort_order);
CREATE UNIQUE INDEX ux_wood_unknown ON wood_option(is_unknown) WHERE is_unknown = 1;

CREATE TABLE shop (
  id         INTEGER PRIMARY KEY,
  label      TEXT    NOT NULL UNIQUE,
  sort_order INTEGER NOT NULL,
  url        TEXT,
  notes      TEXT,
  is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_shop_sort ON shop(sort_order);

INSERT INTO diameter_option(id,label,sixty_fourths,sort_order,is_unknown) VALUES
  (0,'Unknown',NULL,999,1), (1,'11/32"',22,1,0), (2,'5/16"',20,2,0), (3,'23/64"',23,3,0);
INSERT INTO wood_option(id,label,sort_order,is_unknown) VALUES
  (0,'Unknown',999,1), (1,'Northern Pine',1,0), (2,'Oxford Cedar',2,0),
  (3,'Spruce',3,0), (4,'Douglas Fir',4,0);

-- 2.3 Batch. nominal_spine_label is DISPLAY ONLY and must never feed the
-- analysis -- the workbook itself carries a 1 lb gap between the label
-- ("55-60#") and the analysis spec floor (specMin = 54.0).

CREATE TABLE batch (
  id                  INTEGER PRIMARY KEY,
  batch_no            INTEGER NOT NULL UNIQUE,
  seq_width           INTEGER NOT NULL DEFAULT 2 CHECK (seq_width BETWEEN 2 AND 5),
  nominal_spine_label TEXT,
  nominal_min_lb      INTEGER,
  nominal_max_lb      INTEGER,
  diameter_id         INTEGER NOT NULL DEFAULT 0 REFERENCES diameter_option(id),
  wood_id             INTEGER NOT NULL DEFAULT 0 REFERENCES wood_option(id),
  shop_id             INTEGER REFERENCES shop(id),
  purchase_date       TEXT CHECK (purchase_date IS NULL
                        OR purchase_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  expected_count      INTEGER NOT NULL DEFAULT 0 CHECK (expected_count >= 0),
  description         TEXT,
  entry_mode          TEXT NOT NULL DEFAULT 'per_shaft'
                        CHECK (entry_mode IN ('per_shaft','per_field')),
  entry_pass          TEXT CHECK (entry_pass IS NULL OR entry_pass IN ('spine','weight','straightness')),
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- 2.6 Analysis parameters. A row per named preset, exactly one default.
-- Every quantity carries its unit suffix -- centipounds and millipounds
-- must never meet in one expression.

CREATE TABLE param_set (
  id             INTEGER PRIMARY KEY,
  name           TEXT    NOT NULL UNIQUE,
  is_default     INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),

  spine_tol_mlb  INTEGER NOT NULL,
  weight_tol_cg  INTEGER NOT NULL,
  objective      TEXT    NOT NULL DEFAULT 'MAX_DOZENS'
                   CHECK (objective IN ('MAX_SET','MAX_DOZENS')),
  dozen_size     INTEGER NOT NULL DEFAULT 12 CHECK (dozen_size >= 2),

  -- Flag / reporting only. Never inputs to the solver.
  spec_min_mlb   INTEGER NOT NULL,
  spec_max_mlb   INTEGER NOT NULL,
  ab_tol_cp      INTEGER NOT NULL,
  min_group_size INTEGER NOT NULL DEFAULT 3 CHECK (min_group_size >= 1),

  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (spec_min_mlb <= spec_max_mlb),
  CHECK (spine_tol_mlb >= 0 AND weight_tol_cg >= 0 AND ab_tol_cp >= 0)
);
CREATE UNIQUE INDEX ux_param_default ON param_set(is_default) WHERE is_default = 1;

INSERT INTO param_set(id,name,is_default,spine_tol_mlb,weight_tol_cg,objective,
                      spec_min_mlb,spec_max_mlb,ab_tol_cp,min_group_size)
VALUES (1,'Workbook defaults',1, 3000, 50, 'MAX_DOZENS', 54000, 60000, 100, 3);

-- 2.7 Entry rules: grain, plausibility and unit-conversion bands, singleton.

CREATE TABLE entry_rule (
  id                 INTEGER PRIMARY KEY CHECK (id = 1),
  spine_max_dp       INTEGER NOT NULL DEFAULT 2,
  weight_max_dp      INTEGER NOT NULL DEFAULT 2,
  spine_grain_cp     INTEGER NOT NULL DEFAULT 50,
  weight_grain_cg    INTEGER NOT NULL DEFAULT 1,
  spine_hard_min_cp  INTEGER NOT NULL DEFAULT 1000,
  spine_hard_max_cp  INTEGER NOT NULL DEFAULT 20000,
  spine_warn_min_cp  INTEGER NOT NULL DEFAULT 3000,
  spine_warn_max_cp  INTEGER NOT NULL DEFAULT 9000,
  weight_hard_min_cg INTEGER NOT NULL DEFAULT 100,
  weight_hard_max_cg INTEGER NOT NULL DEFAULT 20000,
  weight_warn_min_cg INTEGER NOT NULL DEFAULT 1500,
  weight_warn_max_cg INTEGER NOT NULL DEFAULT 3500,
  batch_outlier_spine_cp   INTEGER NOT NULL DEFAULT 1000,
  batch_outlier_weight_cg  INTEGER NOT NULL DEFAULT 300,
  grains_per_gram    TEXT NOT NULL DEFAULT '15.4324'
);
INSERT INTO entry_rule(id) VALUES (1);

-- 2.8 Sets and consumption. Membership lives on shaft.consumed_set_id, not
-- a join table: one nullable column gives NULL = available, uniqueness of
-- membership for free, and a plain WHERE for the 409 concurrency check.

CREATE TABLE arrow_set (
  id                    INTEGER PRIMARY KEY,
  name                  TEXT    NOT NULL UNIQUE,
  target_size           INTEGER NOT NULL DEFAULT 12 CHECK (target_size >= 1),
  diameter_id           INTEGER NOT NULL REFERENCES diameter_option(id),
  wood_id               INTEGER NOT NULL REFERENCES wood_option(id),
  param_set_id          INTEGER REFERENCES param_set(id),
  analysis_cache_key    TEXT,
  pool_version_at_build INTEGER NOT NULL,
  idempotency_key       TEXT UNIQUE,
  notes                 TEXT,
  created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  disbanded_at          TEXT
);
CREATE INDEX ix_set_partition ON arrow_set(diameter_id, wood_id);

-- 2.4 Shaft -- the core table. diameter_id/wood_id are NOT NULL DEFAULT 0
-- (the Unknown sentinel), because a NULL partition key cannot be grouped
-- or addressed in a URL. straightness stays genuinely nullable: NULL means
-- "not yet assessed" and it is never a partition key.

CREATE TABLE shaft (
  id              INTEGER PRIMARY KEY,
  batch_id        INTEGER NOT NULL REFERENCES batch(id) ON DELETE RESTRICT,
  seq             INTEGER NOT NULL CHECK (seq >= 1),
  label           TEXT    NOT NULL UNIQUE,

  diameter_id     INTEGER NOT NULL DEFAULT 0 REFERENCES diameter_option(id),
  wood_id         INTEGER NOT NULL DEFAULT 0 REFERENCES wood_option(id),

  -- Materialised from shaft_spine_reading by core.derive, same transaction.
  spine_count     INTEGER NOT NULL DEFAULT 0 CHECK (spine_count  >= 0),
  spine_sum_cp    INTEGER NOT NULL DEFAULT 0 CHECK (spine_sum_cp >= 0),
  spine_min_cp    INTEGER,
  spine_max_cp    INTEGER,
  avg_spine_mlb   INTEGER,
  spine_spread_cp INTEGER,

  weight_cg       INTEGER CHECK (weight_cg IS NULL OR weight_cg > 0),
  weight_text     TEXT,
  weight_unit     TEXT CHECK (weight_unit IS NULL OR weight_unit IN ('g','gr')),

  straightness    TEXT CHECK (straightness IS NULL
                    OR straightness IN ('EXCELLENT','OK','BAD','JUNK')),
  notes           TEXT,

  consumed_set_id INTEGER REFERENCES arrow_set(id) ON DELETE SET NULL,
  consumed_at     TEXT,

  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),

  UNIQUE (batch_id, seq),
  CHECK (spine_count = 0 OR (avg_spine_mlb   IS NOT NULL
                         AND spine_min_cp    IS NOT NULL
                         AND spine_max_cp    IS NOT NULL
                         AND spine_spread_cp IS NOT NULL)),
  CHECK (spine_count = 0 OR spine_spread_cp = spine_max_cp - spine_min_cp),
  -- The frozen slice-2 identity, enforced on every write.
  CHECK (spine_count <> 2 OR avg_spine_mlb = spine_sum_cp * 5),
  CHECK ((consumed_set_id IS NULL) = (consumed_at IS NULL)),
  CHECK (weight_cg IS NULL OR (weight_text IS NOT NULL AND weight_unit IS NOT NULL))
);

CREATE INDEX ix_shaft_batch_seq ON shaft(batch_id, seq);
CREATE INDEX ix_shaft_label     ON shaft(label);
CREATE INDEX ix_shaft_set       ON shaft(consumed_set_id);
CREATE INDEX ix_shaft_partition ON shaft(diameter_id, wood_id);

-- The covering index slice 2 scans to build one partition's input, in sort
-- order, with no arithmetic and no post-filter.
CREATE INDEX ix_shaft_analysis ON shaft(diameter_id, wood_id, avg_spine_mlb, weight_cg, id)
  WHERE consumed_set_id IS NULL
    AND avg_spine_mlb IS NOT NULL
    AND weight_cg     IS NOT NULL
    AND (straightness IS NULL OR straightness <> 'JUNK');

CREATE INDEX ix_shaft_weight   ON shaft(weight_cg);
CREATE INDEX ix_shaft_avgspine ON shaft(avg_spine_mlb);

-- 2.5 Spine readings -- a child table from day one. SPEC!A54 asks for 3+
-- readings; the general average formula in core.derive degenerates exactly
-- to the frozen 2-reading rule (spine_sum_cp * 5), proved in
-- tests/test_derive.py. Slice 1's UI and API use only ordinals 1 and 2.

CREATE TABLE shaft_spine_reading (
  id           INTEGER PRIMARY KEY,
  shaft_id     INTEGER NOT NULL REFERENCES shaft(id) ON DELETE CASCADE,
  ordinal      INTEGER NOT NULL CHECK (ordinal >= 1),   -- 1='A', 2='B', 3+ reserved
  value_cp     INTEGER NOT NULL CHECK (value_cp > 0),
  entered_text TEXT    NOT NULL,
  measured_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (shaft_id, ordinal)
);
CREATE INDEX ix_reading_shaft ON shaft_spine_reading(shaft_id);

-- Pivot view: keeps the entry grid and export a plain SELECT.
CREATE VIEW shaft_entry_v AS
SELECT s.id, s.batch_id, b.batch_no, s.seq, s.label, s.diameter_id, s.wood_id,
       ra.value_cp AS spine_a_cp, ra.entered_text AS spine_a_text,
       rb.value_cp AS spine_b_cp, rb.entered_text AS spine_b_text,
       s.spine_count, s.spine_sum_cp, s.spine_min_cp, s.spine_max_cp,
       s.avg_spine_mlb, s.spine_spread_cp,
       s.weight_cg, s.weight_text, s.weight_unit,
       s.straightness, s.notes, s.consumed_set_id, s.consumed_at, s.updated_at
FROM shaft s
JOIN batch b ON b.id = s.batch_id
LEFT JOIN shaft_spine_reading ra ON ra.shaft_id = s.id AND ra.ordinal = 1
LEFT JOIN shaft_spine_reading rb ON rb.shaft_id = s.id AND rb.ordinal = 2;

-- pool_version is bumped by trigger only, never by application code, so a
-- forgotten bump can never silently serve a stale analysis. It is opaque
-- and monotonic: a 100-shaft import bumps it roughly 300 times.

CREATE TRIGGER trg_shaft_ai   AFTER INSERT ON shaft
  BEGIN UPDATE app_meta SET int_value = int_value + 1 WHERE key = 'pool_version'; END;
CREATE TRIGGER trg_shaft_au   AFTER UPDATE ON shaft
  BEGIN UPDATE app_meta SET int_value = int_value + 1 WHERE key = 'pool_version'; END;
CREATE TRIGGER trg_shaft_ad   AFTER DELETE ON shaft
  BEGIN UPDATE app_meta SET int_value = int_value + 1 WHERE key = 'pool_version'; END;
CREATE TRIGGER trg_reading_ai AFTER INSERT ON shaft_spine_reading
  BEGIN UPDATE app_meta SET int_value = int_value + 1 WHERE key = 'pool_version'; END;
CREATE TRIGGER trg_reading_au AFTER UPDATE ON shaft_spine_reading
  BEGIN UPDATE app_meta SET int_value = int_value + 1 WHERE key = 'pool_version'; END;
CREATE TRIGGER trg_reading_ad AFTER DELETE ON shaft_spine_reading
  BEGIN UPDATE app_meta SET int_value = int_value + 1 WHERE key = 'pool_version'; END;

-- 2.9 Import staging. Staged in SQLite, not an in-process dict, so a
-- preview survives a --reload restart and every import leaves an audit row.

CREATE TABLE import_run (
  id              INTEGER PRIMARY KEY,
  token           TEXT    NOT NULL UNIQUE,
  idempotency_key TEXT    UNIQUE,
  source_name     TEXT    NOT NULL,
  format          TEXT    NOT NULL CHECK (format IN ('csv','json','xlsx')),
  mode            TEXT    NOT NULL CHECK (mode IN ('create_only','update_existing','replace_batch')),
  row_count       INTEGER NOT NULL,
  created_count   INTEGER NOT NULL DEFAULT 0,
  updated_count   INTEGER NOT NULL DEFAULT 0,
  status          TEXT    NOT NULL CHECK (status IN ('previewed','committed','failed','expired')),
  payload_json    TEXT    NOT NULL,
  report_json     TEXT,
  created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  committed_at    TEXT
);
