#!/usr/bin/env bash
# Usage: scripts/dbrun.sh <command...>
# Runs a command while holding the project-wide DB lock. ALL pytest runs that touch the database (anything with
# integration tests) must go through this: the tests share ONE schema (ledgermind_test) and their module fixtures
# empty it, so two runs at the same time would destroy each other's data.
LOCK=/c/temp/Account/.venv/db.lock.d
until mkdir "$LOCK" 2>/dev/null; do sleep 3; done
trap 'rmdir "$LOCK" 2>/dev/null' EXIT INT TERM
"$@"
