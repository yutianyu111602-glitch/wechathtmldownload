# Execution Plan

Updated: 2026-05-31 06:10 CST

## S1 Inventory

1. Add a read-only script that discovers CloudRun routes, mini-program pages, pipeline/deploy/upload entries, external-link files, data-package files, and field alias hit groups.
2. Add tests using a temporary fixture repo.
3. Run the script on the real repo and save JSON/Markdown output.
4. Update longrun docs and loop handoff.

## S2 Field Contract

1. Use S1 output plus subagent C output.
2. Define canonical fields for IDs, venue, geo, source, relations, and outlinks.
3. Add validators before runtime mutation.

## S3 Coordinates

1. Build an accepted/review/blocked queue from current release and venue registry.
2. Use provider APIs only for unresolved rows and store status/evidence, not raw secrets.
3. Patch only rows with provider/source-backed confirmation.

## S4 Mobile Mixtape/Outlinks

1. Define data contract for external music links.
2. Add backend pass-through metadata.
3. Add mobile UI that opens/copies original links and labels copyright-safe behavior.
4. Test buttons and fallback paths.

## S5 Production

1. Run CloudRun tests, mini-program Node tests, clean-ci quality gate, and public smoke.
2. Deploy/upload only when there is a verified runtime/data delta.
3. Record exact version, package, logs, and public status.

## S6 SSOT

1. Update project docs and WSL master doc.
2. Write loop handoff and scorecard.
3. Keep next resume cursor exact.
