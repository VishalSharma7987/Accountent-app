Step 3.4/3.5 (package C, ITC register): engine/gst_itc.py (classify, deadline, 180-day share, reversal/reclaim arithmetic), services/gst_itc.py (on_post, on_reverse, evidence, confirm, tag-blocked, apply_2b_result for D, set_claimed_period for E, exposure, reversal/reclaim drafts, register tie), repository, API + schemas.
Tests: 32 engine unit tests; 6 integration tests in tests/integration/test_gst_itc_register.py run via dbrun.sh (pass). Full suite NOT run (owner instruction). ruff clean.
Dependencies: B must call hooks on post/reverse (integration tests call on_post by hand); A for registrations/ledger roles (tests insert them by SQL).
Decisions: docs/decisions_parts/C.md. Pending legal: 180-day formula, Section 16(4) annual-return clause, RCM credit timing, 17(5) rows.
