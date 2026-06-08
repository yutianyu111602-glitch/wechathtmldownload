# Loop 016 Handoff

Time: 2026-05-31 09:16 CST

## Completed

- Audited local Tencent geocode signing code against Tencent official WebService key/signature documentation.
- Confirmed the local code sorts GET parameters, signs raw unencoded parameters with the same request path, URL-encodes final parameters, and uses `x-legacy-url-decode:no`.
- Ran focused geocode tests.
- Wrote report: `reports\WEEKLY_TENCENT_GEOCODE_SIGNATURE_AUDIT_20260531.md`.

## Verification

- `python -m pytest tools\stage7_rewrite\tests\test_geocode_weekly_activity_places.py -q` -> `19 passed`.
- Official docs checked:
  - `https://lbs.qq.com/faq/serverFaq/webServiceKey`
  - `https://lbs.qq.com/service/webService/webServiceGuide/search/webServiceSearch`

## Decision

`weekly_tencent_geocode_signature_code_aligned_config_blocked`

Treat Tencent status `111` as a key/SK/control-plane configuration blocker unless a new official-doc counterexample appears.

## Boundaries

- No code change.
- No key/SK value printed or written.
- No coordinate/address write.
- No CloudRun deploy.
- No mini-program upload/review.
- No DB/graph/vector mutation.

## Next

Coordinate repair now needs a valid Tencent key/SK pairing or another provider/source with a strong Rust Club street-level match. Continue to keep `rust_club_daqing` as `pending_geocode`.
