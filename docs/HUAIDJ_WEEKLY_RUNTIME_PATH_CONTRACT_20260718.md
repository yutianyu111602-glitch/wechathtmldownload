# HUAIDJ weekly runtime path contract

Status: source contract for the recovery candidate. Applying the Hermes
installer and completing a real publish remain separate operational gates.

## Authority boundary

- Source checkouts are immutable code. Their bundled
  `services/weekly_activity_cloudrun/data/current_release` is development data,
  never the default production baseline.
- Mutable production state lives under
  `F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun`.
- The canonical data root is `data`; the canonical full baseline is
  `data\current_release`; deploy staging is written under sibling `work`.
- Resolution order is explicit parameter, Process/User environment, then the
  canonical runtime path. Checkout fallback is allowed only for non-deploy
  development when the runtime SSOT is absent.

## Environment and parameters

| Meaning | Environment | PowerShell parameter |
| --- | --- | --- |
| Incremental merge baseline | `HUAIDJ_CURRENT_RELEASE_DIR` | `IncrementalBaseApiDir` |
| Last published package used for VL delta | `HUAIDJ_PUBLISHED_API_DIR` | `PublishedApiDir` |
| CloudRun mutable data root | `HUAIDJ_CLOUDRUN_DATA_ROOT` | `CloudRunDataRoot` |
| CloudRun deploy work root | `HUAIDJ_CLOUDRUN_WORK_ROOT` | `CloudRunWorkRoot` |
| Current temporary proxy | `HUAIDJ_PROXY_URL` | `ProxyUrl` |

`PublishedApiDir` and `IncrementalBaseApiDir` are separate contracts. They
default to the same current-release SSOT, but a caller may make the distinction
explicit. A deployment validates both and rejects a published package that is
inside the checkout or behind the online manifest.

## Deployment gates

Before a backend write, the pipeline must prove all of the following:

1. runtime data/current/work paths are outside the source checkout;
2. `current.json` and `manifest.json` exist and have matching item counts;
3. the authoritative local baseline is not smaller than the public manifest;
4. the candidate is not smaller than the authoritative base or online package;
5. the CloudRun context was baked from the external runtime data root; and
6. the existing post-deploy smoke and pagination readback pass.

The public preflight uses FlClash at `127.0.0.1:7890` by default during this
temporary recovery period. This does not change the older network SSOT.

## Exporter credentials

Docker exporter/mptext authentication is short-lived runtime state. Scripts
may read `MPTEXT_AUTH_KEY` from the process environment, but tracked scripts,
documentation, reports, and examples must not contain a literal. Discover and
validate the latest Docker exporter session before an exporter run; never reuse
an old key from Git history or a checkpoint.
