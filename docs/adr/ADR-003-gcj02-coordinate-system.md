# ADR-003: GCJ-02 Coordinate System

**Date**: 2026-06-10
**Status**: Accepted

## Context

The mini-program displays event venues on a map (Tencent Maps). We need to choose
a coordinate system for storing and serving geo coordinates.

## Decision

Use **GCJ-02** (国测局坐标) as the sole coordinate system for all geo data.

## Rationale

1. **Legal requirement**: China mandates GCJ-02 for all map services. Using WGS-84
   on Chinese map tiles causes visible offset (100-500m shift).
2. **Tencent Maps compatibility**: The mini-program uses Tencent Maps SDK which
   natively expects GCJ-02 coordinates.
3. **Consistency**: All coordinates in the pipeline (`geo_lat`, `geo_lng`,
   `venue_lat`, `venue_lng`) use GCJ-02. No runtime conversion needed.
4. **Source of truth**: `geo_source` field records how coordinates were obtained
   (e.g., `tencent_map_picker_user_confirmed`). Confirmed coordinates are
   considered authoritative.

## Consequences

- **Positive**: No coordinate conversion at runtime, legally compliant, accurate on Tencent Maps
- **Negative**: Coordinates are offset from true WGS-84 positions — cannot be used directly
  with Google Maps or OpenStreetMap without conversion
- **Note**: The `geo_coord_system` field is always `"GCJ-02"` in event data.
  Any consumer needing WGS-84 must apply the inverse transform.
