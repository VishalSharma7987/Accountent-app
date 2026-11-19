-- Seed: Phase 6 depreciation rule tables (income-tax block rates, the half-rate rule, Companies Act Schedule II useful lives).
-- Safe to run more than once (INSERT ... ON CONFLICT DO UPDATE by key). Schema-agnostic.
-- STATUS (docs/PHASE6_LEGAL_VALUES.md): nothing here is 'verified'. incometaxindia.gov.in / indiacode.nic.in were not read in step 6.0.
--   secondary_verified = the figure appears on several secondary pages found by web search (cleartax.in, legaldev.in, taxgarden.in,
--                        5paisa.com, motilaloswal.com) for the Income-tax Act 1961 rate chart;
--   pending            = recalled from the 1961-Act Appendix I / Companies Act 2013 Schedule II, or sources disagree, or it is the
--                        Income-tax Act 2025 row (the section and schedule numbers of the 2025 Act are reported differently by the
--                        sources: s.33 / s.34 / s.35, "Schedule II" / "XIV"; the rates are reported as carried over from the 1961 Act).
-- Rows for FY 2025-26 and before use the 1961 Act (to 31-03-2026); rows from 01-04-2026 use the 2025 Act. The engine picks the row
-- by the financial year's end date (the date the depreciation is claimed for), never a hardcoded rate.

INSERT INTO dep_it_block_rates (block_key, description, act, rate, effective_from, effective_to, source_reference, verification_status, notes)
VALUES
    ('building_residential', 'Buildings - residential (not hotels / boarding houses)', 'it_act_1961', 5, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part A, Block 1(i) - recalled; official text not read', 'pending', 'Secondary pages quote 5% for residential buildings; one page gives 10% for all buildings.'),
    ('building_other', 'Buildings - other than residential (office, shop, factory)', 'it_act_1961', 10, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part A, Block 1(ii) - recalled; official text not read', 'secondary_verified', 'Secondary pages: 10%.'),
    ('building_temporary', 'Buildings - temporary structures (wooden)', 'it_act_1961', 40, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part A, Block 1(iii) - recalled; official text not read', 'pending', NULL),
    ('furniture_fittings', 'Furniture and fittings (including electrical fittings)', 'it_act_1961', 10, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part A, Block 2; secondary pages (cleartax.in, legaldev.in)', 'secondary_verified', NULL),
    ('plant_machinery_general', 'Plant and machinery - general rate', 'it_act_1961', 15, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part A, Block 3(ii); secondary pages (cleartax.in, legaldev.in)', 'secondary_verified', NULL),
    ('motor_car', 'Motor cars (not used in a business of running them on hire)', 'it_act_1961', 15, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part A, Block 3 - recalled; official text not read', 'pending', 'Block 3(ii) general rate 15% as recalled.'),
    ('motor_vehicle_hire', 'Motor buses, lorries and taxis used in a business of running them on hire', 'it_act_1961', 30, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part A, Block 3(iii) - recalled; official text not read', 'pending', NULL),
    ('computers_software', 'Computers including computer software', 'it_act_1961', 40, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part A, Block 5; secondary pages (cleartax.in, legaldev.in)', 'secondary_verified', NULL),
    ('intangible_assets', 'Intangible assets (know-how, patents, copyrights, trademarks, licences, franchises)', 'it_act_1961', 25, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part B; secondary pages (cleartax.in, legaldev.in)', 'secondary_verified', NULL),
    ('pollution_control', 'Pollution control equipment', 'it_act_1961', 40, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Rules 1962 Appendix I, Part A, Block 3 (specified plant) - recalled; official text not read', 'pending', NULL),

    ('building_residential', 'Buildings - residential (not hotels / boarding houses)', 'it_act_2025', 5, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('building_other', 'Buildings - other than residential (office, shop, factory)', 'it_act_2025', 10, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('building_temporary', 'Buildings - temporary structures (wooden)', 'it_act_2025', 40, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('furniture_fittings', 'Furniture and fittings (including electrical fittings)', 'it_act_2025', 10, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('plant_machinery_general', 'Plant and machinery - general rate', 'it_act_2025', 15, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('motor_car', 'Motor cars (not used in a business of running them on hire)', 'it_act_2025', 15, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('motor_vehicle_hire', 'Motor buses, lorries and taxis used in a business of running them on hire', 'it_act_2025', 30, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('computers_software', 'Computers including computer software', 'it_act_2025', 40, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('intangible_assets', 'Intangible assets (know-how, patents, copyrights, trademarks, licences, franchises)', 'it_act_2025', 25, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('pollution_control', 'Pollution control equipment', 'it_act_2025', 40, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation schedule - section / schedule number not verified', 'pending', 'Reported as carried over from the 1961 Act.')
ON CONFLICT (block_key, act, effective_from) DO UPDATE SET description = EXCLUDED.description, rate = EXCLUDED.rate,
    effective_to = EXCLUDED.effective_to, source_reference = EXCLUDED.source_reference,
    verification_status = EXCLUDED.verification_status, notes = EXCLUDED.notes;

-- half-rate rule: an addition put to use for FEWER than 180 days in the year gets 50% of the block rate
INSERT INTO dep_it_rules (rule_key, act, rule_value, effective_from, effective_to, source_reference, verification_status, notes)
VALUES
    ('half_rate_days', 'it_act_1961', 180, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Act 1961 s.32(1) 2nd proviso; secondary pages (cleartax.in, compliancecalendar.in, taxgarden.in)', 'secondary_verified', 'Fewer than 180 days -> half; 180 days or more -> full.'),
    ('half_rate_percent', 'it_act_1961', 50, DATE '2025-04-01', DATE '2026-03-31',
     'Income-tax Act 1961 s.32(1) 2nd proviso; secondary pages (cleartax.in, compliancecalendar.in, taxgarden.in)', 'secondary_verified', NULL),
    ('half_rate_days', 'it_act_2025', 180, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation section (reported as s.33; not verified)', 'pending', 'Reported as carried over from the 1961 Act.'),
    ('half_rate_percent', 'it_act_2025', 50, DATE '2026-04-01', NULL,
     'Income-tax Act 2025 depreciation section (reported as s.33; not verified)', 'pending', 'Reported as carried over from the 1961 Act.')
ON CONFLICT (rule_key, act, effective_from) DO UPDATE SET rule_value = EXCLUDED.rule_value, effective_to = EXCLUDED.effective_to,
    source_reference = EXCLUDED.source_reference, verification_status = EXCLUDED.verification_status, notes = EXCLUDED.notes;

-- Companies Act 2013 Schedule II, Part C: useful life in years (single shift) and the residual ceiling (5% of the original cost).
-- All recalled, none read from the Act in this step: every row is 'pending' and the verification is shown on the depreciation run.
INSERT INTO dep_sched2_classes (class_key, description, useful_life_years, max_residual_percent, effective_from, effective_to, source_reference, verification_status, notes)
VALUES
    ('building_rcc', 'Buildings (other than factory buildings) - RCC frame structure', 60, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('building_other_than_rcc', 'Buildings (other than factory buildings) - other than RCC frame', 30, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('building_factory', 'Factory buildings', 30, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('building_temporary', 'Temporary wooden structures', 3, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('plant_machinery_general', 'Plant and machinery - general (single shift)', 15, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', 'Extra shift depreciation is not modelled.'),
    ('furniture_fittings', 'Furniture and fittings - general', 10, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('office_equipment', 'Office equipment', 5, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('computers_end_user', 'Computers and data processing units - desktops, laptops', 3, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('computers_servers_networks', 'Computers and data processing units - servers and networks', 6, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('motor_car', 'Motor vehicles - motor cars (other than those used in a business of running them on hire)', 8, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('motor_cycle_scooter', 'Motor vehicles - motor cycles, scooters and other mopeds', 10, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('motor_vehicle_hire', 'Motor buses, lorries and taxis used in a business of running them on hire', 6, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL),
    ('electrical_installations', 'Electrical installations and equipment', 10, 5, DATE '2014-04-01', NULL, 'Companies Act 2013 Schedule II Part C (recalled; not read)', 'pending', NULL)
ON CONFLICT (class_key, effective_from) DO UPDATE SET description = EXCLUDED.description, useful_life_years = EXCLUDED.useful_life_years,
    max_residual_percent = EXCLUDED.max_residual_percent, effective_to = EXCLUDED.effective_to, source_reference = EXCLUDED.source_reference,
    verification_status = EXCLUDED.verification_status, notes = EXCLUDED.notes;
