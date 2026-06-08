# Loop 012: Venue Registry Public Fill

Timestamp: 2026-05-09 03:36 CST

## Scope

Registry-only data quality improvement. Did not deploy CloudRun data because published item ids did not change. Did not touch 93k/OCR/Stage7/vector/Dajiala lanes.

## Added Venue Registry Rows

Expanded `tools/stage7_rewrite/registries/weekly_venues_seed.json` from `28` to `34` venues:

- `YUANHE 原核`, Beijing
- `ZhaoDai`, Beijing
- `PILLBOX Beijing`, Beijing
- `Cici Park`, Chongqing
- `播放室`, Xi'an
- `JAR这儿`, Xi'an

## Source Evidence

- Yuanhe: LocalHub + RA venue line.
  - `https://localhub.to/beijing/venue/yuanhe/?lang=en`
  - `https://ra.co/events/2379464`
- Zhao Dai: LocalHub venue line.
  - `https://localhub.to/beijing/venue/zhao-dai`
- Pillbox Beijing: SESH/Likdo venue lines.
  - `https://sesh.sx/e/927156`
  - `https://likdo.asia/venue/331/`
- Cici Park: RA/LocalHub venue lines.
  - `https://fr.ra.co/events/2412256`
  - `https://localhub.to/chongqing/venue/cici-park/?lang=en`
- ROP/播放室: public profile address.
  - `https://www.pixnoy.com/profile/rop_xian/`
- JAR: current WeChat source text includes the full 粉巷 address.

## Result

Rebuilt current window to:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY34_CURRENT_20260509`

Result:

- `item_count`: `22`
- `venue_registry_count`: `34`
- `missing_address`: `17` (was `24`)
- `missing_city`: `64` (was `76`)
- `missing_time`: `38` (was `30`)
- `outside_date_window`: `288`

The increase in `missing_time` is expected: rows that previously stopped at missing city/address now advance to the next gate and reveal missing time.

Published ids did not change, so the current CloudBase data release was not replaced.

## Verification

- registry validator: `ok=true`, `error_count=0`
- Python weekly registry/API tests: `15/15` passed
- old vs new published ids: no added ids, no removed ids

## Next Data Work

The remaining current-window lift is mostly time extraction, not address lookup. Use source article text/OCR or a bounded LLM enrichment pass later; do not invent default times.
