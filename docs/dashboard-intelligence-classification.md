# Dashboard Intelligence Cache Classification

## Current Classification

`dashboard_intelligence.json` is a generated runtime cache with a dashboard
fallback role. It is not source data, seed data, or a test fixture.

## Why It Is Currently Tracked

The file was already tracked before this classification work. Its root-level
JSON snapshot shape made it look similar to other legacy runtime mirrors that
were historically committed for local inspection or operator continuity.

Keeping it tracked during the audit avoided changing dashboard startup behavior
before explicit missing-file coverage existed.

## Evidence Summary

- `dashboard_server.py:40` defines `INTELLIGENCE_PATH` as
  `dashboard_intelligence.json`.
- `dashboard_server.py:1050` defines `refresh_intelligence()`.
- `dashboard_server.py:1068` writes generated intelligence payloads to
  `INTELLIGENCE_PATH`.
- `dashboard_server.py:1072` defines `get_intelligence()`.
- `dashboard_server.py:1074` reads `INTELLIGENCE_PATH` as a cached payload.
- `dashboard_server.py:1098` builds deterministic fallback intelligence when
  the cache is missing or unusable and refresh is not forced.
- `dashboard_data.py:17` returns an empty dictionary for a missing JSON path.
- `tests/test_dashboard_intelligence_cache.py` covers missing-cache fallback
  behavior without using the tracked cache file.

## Read Path Summary

`get_intelligence()` reads `INTELLIGENCE_PATH` through the dashboard data
adapter. If a cached payload has a usable `generatedAtUtc` value and is fresh
enough, the dashboard returns it. If the cache is stale, the dashboard returns
the stale payload with a refresh marker while starting a background refresh.

## Write Path Summary

`refresh_intelligence()` builds a new intelligence payload from fetched news and
either local AI assessment or deterministic fallback logic. It writes the result
to `INTELLIGENCE_PATH`.

## Missing-File Behavior

When `dashboard_intelligence.json` is missing, the data adapter returns an empty
dictionary. `get_intelligence()` then returns deterministic fallback
intelligence containing the dashboard structural keys and starts a background
refresh. The missing-file regression test redirects `INTELLIGENCE_PATH` to a
temporary missing path, stubs external news calls, prevents the background
worker from running, and asserts that the read path does not create the cache
file.

## Safety Rule

Do not treat `dashboard_intelligence.json` as source, seed, or fixture data. It
is generated dashboard runtime state and should not be used to define expected
trading, execution, engine, or dashboard behavior.

## Future Action

After this classification and regression coverage lands, remove the tracked file
only in a separate small cleanup commit:

```bash
git rm --cached dashboard_intelligence.json
```

Then add `dashboard_intelligence.json` to `.gitignore`. Preserve any local copy
that exists on an operator machine.

## Rollback Plan

If removing the tracked cache later causes an unexpected dashboard issue, restore
the cleanup commit or re-add a known local cache file while investigating. The
missing-file regression test should remain because it documents the intended
fallback contract.
