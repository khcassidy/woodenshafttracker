-- "Grain" collided with "grains" (gr), already the archery weight unit
-- used elsewhere (weightGr, grains_per_gram). These two columns are a
-- different concept entirely: the expected reading increment, e.g. spine
-- rounds to the nearest 0.5 lb. Renamed to "step" to remove the collision.

ALTER TABLE entry_rule RENAME COLUMN spine_grain_cp TO spine_step_cp;
ALTER TABLE entry_rule RENAME COLUMN weight_grain_cg TO weight_step_cg;
