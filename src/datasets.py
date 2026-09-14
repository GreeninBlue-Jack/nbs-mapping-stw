"""
Master dataset registry for the NbS opportunity mapping pipeline.

Single source of truth for all datasets used across the six (plus one experimental)
NbS types. All code that needs to know about datasets imports from here.

Configuration
-------------
INCLUDE_EXPERIMENTAL controls whether experimental entries are visible to the
audit script and pipeline. Set True during development; False for client deliverables
until an experimental NbS type is formally activated.

Schema — standard fields (all entries)
---------------------------------------
name           : Human-readable dataset name.
category       : 'opportunity', 'constraint', 'supplementary', or 'multi'
                 ('multi' means the same download feeds both constraint and
                 supplementary uses — see derived_uses).
nbs_types      : list[str] — NbS types that use this dataset. ["all"] means every type.
description    : One-line description of what the dataset represents in the pipeline.
access_method  : One of ACCESS_METHODS below. Determines how the audit script probes
                 the dataset and how the pipeline downloads it.
coverage       : Spatial jurisdiction of the dataset. One of:
                   'england' — England only (EA, Natural England, FC England, WWNP)
                   'gb'      — Great Britain (UKCEH, Ordnance Survey, BGS)
                   'uk'      — United Kingdom
                   'wales'   — Wales only
source_url     : Canonical landing page (for manual_download / requires_login).
                 Not set for arcgis_featureserver / wfs_direct entries.
notes          : Caveats, licence notes, open questions.
experimental   : bool (default False). True = gated by INCLUDE_EXPERIMENTAL.

Schema — access_method-specific fields
----------------------------------------
wfs_direct:
    wfs_url         : Full WFS URL including /wfs suffix
    wfs_layer       : OGC layer type name (from GetCapabilities)
    dataset_id      : DEFRA dataset GUID (informational reference)
    wfs_cql_filter  : str (optional) — server-side CQL filter passed as the CQL_FILTER
                      parameter on GetFeature requests. Combined with the AOI BBOX filter.
                      Example: "risk_band IN ('High','Medium')" for RoFSW NaFRA2.
    wfs_geom_field  : str (optional) — WFS geometry column name. Required when
                      wfs_cql_filter is set, so the AOI BBOX can be embedded in the
                      CQL expression (BBOX(geom_field,...)) rather than passed as a
                      separate BBOX parameter (which can cause 500 errors on GeoServer
                      when combined with CQL_FILTER). Default: 'the_geom'.

ogc_api: (DSP OGC API Features — preferred for DENSE layers; see Brief 11 / doc 08 §4)
    ogc_url         : OGC API base, ".../geoservices/datasets/<GUID>/ogc/features/v1"
    ogc_collection  : Collection id (the part after ':' in the legacy WFS typename)
    ogc_cql_filter  : str (optional) — CQL2-text filter sent as filter=<expr> with
                      filter-lang=cql2-text. Example: "risk_band IN ('High','Medium')".
                      (The simple <prop>=<value> query-param form is NOT supported by
                      the DSP — must use CQL2.)
    ogc_page_size   : int (optional) — features per page (OGC 'limit'). Default 2000.
    wfs_url/wfs_layer : retained for provenance and as a manual fallback; not used when
                      access_method is ogc_api. Fetch + clip handled by
                      src/bulk_access.py::query_ogc_features (vector-only, EPSG:27700).

bulk_download: (static national file — download once, clip-many; see Brief 11)
    bulk_url        : Direct static-file URL (national gpkg / shp / geojson, or a .zip).
    bulk_layer      : str (optional) — layer name inside a multi-layer container, OR the
                      inner file stem to prefer when a .zip holds several vectors.
    bulk_format     : str (optional) — 'gpkg' / 'shp' / 'geojson' / 'zip' (informational).
    bulk_filename   : str (optional) — on-disk cache filename (default: basename of bulk_url).
                      File is cached under <cache_base>/_bulk/<slug>/ (local, un-synced),
                      then clipped to the AOI bbox on read in load_layer.

arcgis_featureserver:
    service_url      : FeatureServer base URL (without trailing /N)
    layer_index      : int — layer index, or None for BGZ-tiled services
    layer_name       : str — layer name from service info
    max_record_count : int — server-side page limit
    bgz_tiled        : bool (optional) — True if service is split by Biogeographical Zone
    bgz_layer_ids    : list[int] (optional) — available BGZ layer indices

arcgis_static_download:
    download_url : Direct ArcGIS Online item download URL
    item_id      : ArcGIS Online item GUID (informational)
    file_format  : 'geotiff', 'gpkg', etc.
    size_mb      : approximate download size (informational)

manual_download / requires_login:
    source_url   : Landing page for HEAD-check

local_file:
    source_url   : Canonical landing page (for documentation / reproducibility)
    file_path    : Repo-relative path to the staged file under data/raw/
                   (e.g. 'data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg')
    file_layer   : str (optional) — for multi-layer containers (.gpkg / .gdb),
                   the named layer to read. Omit for single-layer formats
                   like .shp / .geojson.

pending_url:
    (no URL fields — service URL is not yet known)

Schema — optional extended fields
-----------------------------------
derived_uses   : list[dict]. Present on multi-use datasets (e.g. CEH LCM) where
                 several pipeline roles derive from a single download. Each dict has:
                   use              — machine-readable role key
                   name             — human label
                   category         — 'constraint' or 'supplementary'
                   filter           — SQL-style predicate on primary_attribute, or None
                   nbs_types        — list[str]
                   rationale        — why this filter is applied (optional)
                   scoring_attribute — field to join for supplementary scoring (optional)
primary_attribute : Main attribute field used for filtering (multi-use datasets).

also_used_as_supplementary  : bool. True when an opportunity dataset is also used
                               as a supplementary scoring layer.
nbs_types_supplementary     : list[str]. Which NbS types use it as supplementary.

version  : str (optional). Dataset version string (e.g. 'v4').

phase    : str (optional). Phase tag for staged delivery. Default '1' (current
           Phase 1 critical path). Set to '1.5' to mark a dataset as registered
           but parked as an enhancement option, not yet in the active pipeline
           (e.g. PSGA-licensed upgrades to a Phase 1 open-data input).
"""

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INCLUDE_EXPERIMENTAL = False  # Set False for client deliverables (gates the audit script
# only; the pipeline runners use their own --include-experimental flag). Reset 2026-07-03
# for the delivery phase (review L1).

# Canonical NbS types — peat_restoration is experimental
NBS_TYPES = [
    "pond_pool_scrape",
    "leaky_barriers",
    "bunds",
    "floodplain_reconnection",
    "riparian_buffer_strips",
    "woodland_planting",
    "peat_restoration",  # experimental — NERR149-aligned; awaiting stakeholder go/no-go
]

EXPERIMENTAL_NBS_TYPES = {"peat_restoration"}

ACCESS_METHODS = {
    "wfs_direct",
    "wfs_via_dataset_page",
    "ogc_api",                # DSP OGC API Features (GeoJSON + bbox) — dense layers (Brief 11)
    "bulk_download",          # static national file, cached once, clipped on read (Brief 11)
    "arcgis_featureserver",
    "arcgis_static_download",
    "manual_download",
    "requires_login",
    "local_file",
    "pending_url",
}

COVERAGE_VALUES = {"england", "gb", "uk", "wales"}

_NE_HUB = "https://services.arcgis.com/JJzESW51TqeY9uat/ArcGIS/rest/services"

# ---------------------------------------------------------------------------
# Core dataset registry
# ---------------------------------------------------------------------------

DATASETS = [
    # ------------------------------------------------------------------ #
    # OPPORTUNITY DATA                                                     #
    # ------------------------------------------------------------------ #
    {
        "name": "WWNP Runoff Attenuation Features 1% AEP",
        "category": "opportunity",
        "nbs_types": ["pond_pool_scrape"],
        "description": "Isolated areas of runoff accumulation at 1-in-100 year flood extent",
        "access_method": "bulk_download",   # Brief 17: national gpkg downloaded once, clipped per AOI
        "coverage": "england",
        # ogc_url/ogc_collection retained as a dormant fallback (the OGC route still works):
        "ogc_url": "https://environment.data.gov.uk/geoservices/datasets/fc69965f-684f-463d-b7c9-2471a5d49741/ogc/features/v1",
        "ogc_collection": "WWNP_Runoff_Attenuation_Features_1_percent_AEP",
        # Bulk national GeoPackage (Brief 17): download once to the local cache, validate once, clip per AOI.
        "bulk_url": "https://environment.data.gov.uk/api/file/download?fileDataSetId=acf1f717-9e88-42d3-b2b7-0c15c78ffcf1&fileName=WWNP_Runoff_Attenuation_Features_1_AEP.gpkg.zip",
        # Retained for provenance / manual WFS fallback (not used while access_method=ogc_api):
        "wfs_url": "https://environment.data.gov.uk/spatialdata/wwnp-runoff-attenuation-features-1-percent-aep/wfs",
        "wfs_layer": "dataset-fc69965f-684f-463d-b7c9-2471a5d49741:WWNP_Runoff_Attenuation_Features_1_percent_AEP",
        "wfs_page_size": 5000,
        "dataset_id": "fc69965f-684f-463d-b7c9-2471a5d49741",
        "notes": (
            "Migrated to OGC API Features 2026-06-15 (Brief 11): dense layer that "
            "truncated/overloaded the WFS GML endpoint. OGC route verified live "
            "(numberMatched honoured, bbox+bbox-crs in EPSG:27700, cursor paging)."
        ),
    },
    {
        "name": "OS Open Zoomstack — Waterlines",
        "category": "multi",
        "nbs_types": ["leaky_barriers", "bunds"],
        "description": (
            "OS Open Zoomstack 'waterlines' layer — the canonical watercourse "
            "network used by the original Warwickshire Avon R methodology. "
            "Multi-use: filtered for leaky barriers, unfiltered for bunds."
        ),
        "access_method": "local_file",
        "coverage": "gb",
        "source_url": "https://www.ordnancesurvey.co.uk/products/os-open-zoomstack",
        "file_path": "data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg",
        "file_layer": "waterlines",
        "primary_attribute": "type",
        "notes": (
            "OS Open Zoomstack (OGL) — same GeoPackage as Zoomstack Roads / Railways "
            "(one ~12 GB download serves three registry entries). Schema is minimal: "
            "single attribute 'type' with values 'Local', 'Regional', 'National', "
            "'District'. The Avon model uses this layer two ways — see derived_uses. "
            "Confirmed by inspection of "
            "data/reference/R_Model/Scripts/ConstraintsLayers_prep.R lines 70-76, "
            "OppMapp_LeakyBarriers_v2.R, and OppMapp_BundsCatchmentStorageAreas_v2.R. "
            "Two hidden manual preprocess steps in the original methodology: "
            "(a) 100 m point sampling along Local lines (was a QGIS plugin — "
            "replace with shapely interpolate); (b) multi-type buffering for bunds "
            "(lookup {District: 50, Local: 30, National: 150, Regional: 100} metres). "
            "See docs/methodology/05_waterlines_source_clarification.md."
        ),
        "derived_uses": [
            {
                "use": "leaky_barriers_lines",
                "name": "Local Waterlines (for leaky barriers)",
                "category": "opportunity",
                "filter": "type == 'Local'",
                "nbs_types": ["leaky_barriers"],
                "rationale": (
                    "Leaky barriers are appropriate for small headwater streams. "
                    "The Avon model filters Zoomstack waterlines to type=='Local' "
                    "and samples 100 m points along the filtered lines for "
                    "candidate-site placement (OppMapp_LeakyBarriers_v2.R lines 38-40)."
                ),
            },
            {
                "use": "bunds_all_types",
                "name": "All Waterlines (for bunds, with type-keyed buffer)",
                "category": "opportunity",
                "filter": None,
                "nbs_types": ["bunds"],
                "rationale": (
                    "Bunds use all four 'type' values with a type-keyed buffer "
                    "distance (District: 50 m, Local: 30 m, National: 150 m, "
                    "Regional: 100 m) — see OppMapp_BundsCatchmentStorageAreas_v2.R "
                    "lines 41-47."
                ),
            },
        ],
    },
    {
        "name": "OS MasterMap Water Network (PSGA)",
        "category": "opportunity",
        "nbs_types": ["leaky_barriers", "bunds"],
        "phase": "1.5",
        "description": (
            "OS MasterMap Water Network — premium PSGA-licensed product covering "
            "the full GB hydrological network. Phase 1.5 enhancement option; not "
            "in the Phase 1 critical path (Phase 1 uses OS Open Zoomstack waterlines)."
        ),
        "access_method": "local_file",
        "coverage": "gb",
        "source_url": "https://www.ordnancesurvey.co.uk/products/os-mastermap-water-network-layer",
        "file_path": "data/raw/os_mastermap_water/OS_MasterMap_Water_Network.gdb",
        "file_layer": "WatercourseLink",
        "notes": (
            "OS PSGA-licensed — restricted distribution. Do NOT commit to the public "
            "GitHub repo (data/raw/ is gitignored). Shared by Matt Palmer 2026-05-20 "
            "via the Nature for Water Facility shared docs. "
            "Two layers in the .gdb: HydroNode (645,839 3D Points — network "
            "junctions/sources/outflows) and WatercourseLink (651,016 3D MultiLineStrings "
            "— the network itself). EPSG:27700. Geometry is 3D, will need flattening "
            "to 2D in preprocess. "
            "Schema is much richer than Zoomstack: 'form' "
            "(inlandRiver/canal/drain), 'width' (metres), 'length', 'gradient', "
            "'flowDirect', 'level' (onGroundSurface vs subsurface — culverts), "
            "'watercName' (named rivers), 'catchmentN' (catchment name). "
            "No Strahler order field — if/when this replaces Zoomstack in Phase 1.5, "
            "the hierarchy filter for leaky barriers will use combined form + width "
            "rather than the simple type=='Local' filter on Zoomstack. "
            "See docs/methodology/05_waterlines_source_clarification.md for the "
            "Phase 1 vs Phase 1.5 plan."
        ),
    },
    {
        "name": "Risk of Flooding from Surface Water — Extent >=1% (NaFRA2)",
        "category": "opportunity",
        "nbs_types": ["leaky_barriers", "bunds"],
        "description": (
            "EA NaFRA2 surface-water flooding extent (0 m depth threshold) filtered to "
            ">=1% annual chance (1-in-100). Modern successor to the R model's RoFSW_Extent_1in100. "
            "risk_band High (>=3.3%) + Medium (>=1%) = the 1-in-100 extent."
        ),
        "access_method": "ogc_api",   # migrated off WFS — dense national layer (~274k feat)
        "coverage": "england",
        "ogc_url": "https://environment.data.gov.uk/geoservices/datasets/4e51df30-8437-4a56-92c2-ab14ff6e565b/ogc/features/v1",
        "ogc_collection": "ROFSW_0_0_Hazard",
        # CQL2-text filter (OGC API Part 3). Verified live: filter=risk_band IN (...)
        # honoured (High+Medium only). The simple risk_band=High query param 500s — must use CQL2.
        "ogc_cql_filter": "risk_band IN ('High','Medium')",
        # Retained for provenance / manual WFS fallback (not used while access_method=ogc_api):
        "wfs_url": "https://environment.data.gov.uk/spatialdata/risk-of-flooding-from-surface-water-hazard/wfs",
        "wfs_layer": "dataset-4e51df30-8437-4a56-92c2-ab14ff6e565b:ROFSW_0_0_Hazard",
        "wfs_cql_filter": "risk_band IN ('High','Medium')",
        "wfs_geom_field": "shape",
        "wfs_page_size": 2000,
        "dataset_id": "4e51df30-8437-4a56-92c2-ab14ff6e565b",
        "notes": (
            "Migrated to OGC API Features 2026-06-15 (Brief 11): the densest layer; "
            "page-by-page WFS GML truncated and overloaded the EA server. OGC route "
            "verified live — risk_band IN ('High','Medium') applied server-side via "
            "CQL2 (numberMatched=17884 over the dev AOI). "
            "Confirmed 2026-06-04 via GetFeature (CQL honoured; native EPSG:27700; MultiPolygon). "
            "0 m depth-threshold layer = flooding extent; risk_band High(>=3.3%) + Medium(>=1%) = "
            "the 1-in-100 extent matching the R model's RoFSW_Extent_1in100. Low(>=0.1%) excluded — "
            "that is the 1-in-1000 band the retired legacy FeatureServer entry wrongly used. "
            "~274k features nationally — MUST clip to AOI bbox on fetch; never pull unclipped. "
            "Geometry field 'shape'; attrs risk_band, shape_length, shape_area. "
            "Same service exposes deeper depth layers (ROFSW_0_25/_0_5/_0_75/_1_25/_2_0_Hazard). "
            "See docs/methodology/07_flood_and_waterbody_sources.md."
        ),
    },
    {
        "name": "Flood Map for Planning — Flood Zone 3 (fluvial floodplain)",
        "category": "constraint",
        "nbs_types": ["leaky_barriers"],
        "description": (
            "EA Flood Map for Planning, Flood Zone 3 (1-in-100 fluvial floodplain). Excluded "
            "from leaky-barrier candidates (Brief 23) — a point in a mapped river floodplain is on "
            "a watercourse too big to be a headwater; small upper-catchment streams have no FZ3."
        ),
        "access_method": "ogc_api",   # dense national layer; per-tile OGC (leaky is small)
        "coverage": "england",
        # LIVE product verified 2026-07-30: the historic FZ3-only feed
        # (87446770-d465-11e4-...) was retired ~Apr 2025. Current source is the COMBINED
        # "Flood Map for Planning – Flood Zones" (04532375-...), collection
        # Flood_Zones_2_3_Rivers_and_Sea, with a 'flood_zone' attribute (FZ2/FZ3). Filter to
        # FZ3 via CQL2. (The candidate 1e91e555-... OGC endpoint 404s — do not use.)
        "ogc_url": "https://environment.data.gov.uk/geoservices/datasets/04532375-a198-476e-985e-0579a0a11b47/ogc/features/v1",
        "ogc_collection": "Flood_Zones_2_3_Rivers_and_Sea",
        "ogc_cql_filter": "flood_zone = 'FZ3'",
        "dataset_id": "04532375-a198-476e-985e-0579a0a11b47",
        "notes": (
            "Flood Zone 3 (fluvial + tidal 'Rivers and Sea'; STW is inland so effectively "
            "fluvial). Filtered server-side to flood_zone='FZ3' via OGC API Part 3 CQL2 — "
            "verified live 2026-07-30 (251 FZ3 features over the Trent-near-Nottingham bbox, "
            "all FZ3). Attributes: origin, flood_zone (FZ2/FZ3), flood_source (river/...). "
            "Dense national layer — MUST clip to AOI bbox on fetch. Tuning: FZ2 (1-in-1000) "
            "removes more if FZ3 leaves too much floodplain; intersect with Statutory Main "
            "River if FZ3 over-clips small-stream headwaters (Brief 23 tuning notes)."
        ),
    },
    {
        "name": "WWNP Floodplain Woodland Potential",
        "category": "opportunity",
        "nbs_types": ["floodplain_reconnection"],
        "description": "Areas where floodplain tree planting may be possible and effective",
        "access_method": "ogc_api",   # REVERTED bulk_download -> ogc_api (Brief 21, 2026-07-24):
        # the DSP bulk .gpkg.zip export is INCOMPLETE — 202,651 features nationally but MISSING
        # large STW areas the OGC feed covers (e.g. tile GB104027052280: OGC 199 features vs
        # bulk 0). The Brief 17 bulk switch was never exercised in a full run until the Brief 21
        # SPZ re-run, which surfaced floodplain collapsing 712 -> 211 tiles. Same DSP-bulk-export
        # unreliability that left the sibling Reconnection layer on OGC. Use OGC per tile.
        "coverage": "england",
        "ogc_url": "https://environment.data.gov.uk/geoservices/datasets/d1b028b8-6090-4621-8645-034f01b32403/ogc/features/v1",
        "ogc_collection": "WWNP_Floodplain_Woodland_Potential",
        # Bulk national GeoPackage — DORMANT: the DSP export is spatially incomplete (see above);
        # do NOT switch back to bulk_download until the published server file is fixed.
        "bulk_url": "https://environment.data.gov.uk/api/file/download?fileDataSetId=273894e4-d95b-47cc-a5eb-aec6564cb56c&fileName=WWNP_Floodplain_Woodland_Potential.gpkg.zip",
        # Retained for provenance / manual WFS fallback (not used while access_method=ogc_api):
        "wfs_url": "https://environment.data.gov.uk/spatialdata/wwnp-floodplain-woodland-potential/wfs",
        "wfs_layer": "dataset-d1b028b8-6090-4621-8645-034f01b32403:WWNP_Floodplain_Woodland_Potential",
        "dataset_id": "d1b028b8-6090-4621-8645-034f01b32403",
        "notes": "OGC API Features (Brief 11); bulk_download reverted to OGC in Brief 21 — DSP bulk export incomplete.",
    },
    {
        "name": "WWNP Floodplain Reconnection Potential",
        "category": "opportunity",
        "nbs_types": ["floodplain_reconnection"],
        "description": "Areas of opportunity for floodplain reconnection",
        "access_method": "ogc_api",   # STAYS on OGC — the DSP bulk gpkg export is EMPTY (0 features,
                                      # verified Brief 17 2026-07-02); OGC route works (112k feat full run).
        "coverage": "england",
        "ogc_url": "https://environment.data.gov.uk/geoservices/datasets/e92e50e6-d2c5-4ae7-b824-138e0da0b554/ogc/features/v1",
        "ogc_collection": "WWNP_Floodplain_Reconnection_Potential",
        # Bulk national GeoPackage (Brief 17): the published .gpkg.zip download is an EMPTY GeoPackage
        # on the DSP (0 features) — do NOT switch to bulk_download until the server file is fixed.
        "bulk_url": "https://environment.data.gov.uk/api/file/download?fileDataSetId=e3cf50a7-8701-4967-91d0-c7df615eca60&fileName=WWNP_Floodplain_Reconnection_Potential.gpkg.zip",
        # Retained for provenance / manual WFS fallback (not used while access_method=ogc_api):
        "wfs_url": "https://environment.data.gov.uk/spatialdata/wwnp-floodplain-reconnection-potential/wfs",
        "wfs_layer": "dataset-e92e50e6-d2c5-4ae7-b824-138e0da0b554:WWNP_Floodplain_Reconnection_Potential",
        "dataset_id": "e92e50e6-d2c5-4ae7-b824-138e0da0b554",
        "notes": "Migrated to OGC API Features 2026-06-15 (Brief 11) — dense WWNP layer; WFS GML truncated.",
    },
    {
        "name": "WWNP Riparian Woodland Potential",
        "category": "opportunity",
        "nbs_types": ["riparian_buffer_strips"],
        "description": "Areas of opportunity for riparian planting along watercourses",
        "access_method": "wfs_direct",
        "coverage": "england",
        "wfs_url": "https://environment.data.gov.uk/spatialdata/wwnp-riparian-woodland-potential/wfs",
        "wfs_layer": "dataset-960926b5-84e7-45f0-a38f-8ef58004820e:WWNP_Riparian_Woodland_Potential",
        "dataset_id": "960926b5-84e7-45f0-a38f-8ef58004820e",
        "notes": None,
    },
    {
        "name": "England Woodland Creation Sensitivity",
        "category": "opportunity",
        "nbs_types": ["woodland_planting"],
        "also_used_as_supplementary": True,
        "nbs_types_supplementary": ["woodland_planting"],
        "description": (
            "Forestry Commission sensitivity map for woodland creation — used as both an "
            "opportunity layer (where woodland can go) and a supplementary priority-scoring "
            "layer (sensitivity score as a constraint-modifier) for woodland planting NbS"
        ),
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": "https://services2.arcgis.com/mHXjwgl3OARRqqD4/arcgis/rest/services/England_Woodland_Creation_Full_Sensitivity_Map_v4/FeatureServer",
        "layer_index": 0,
        "layer_name": "England_Woodland_Creation_Full_Sensitivity_Map_v4",
        "max_record_count": 1000,
        "version": "v4",
        "dataset_id": "607b4b94-1e07-43ee-b79d-524010a848b1",
        "notes": (
            "Key attribute: 'sensitivity'. TODO: monitor for v5 release. "
            "Not available via DEFRA DSP WFS — confirmed after two slug-discovery passes. "
            "Brief 17: STAYS on arcgis_featureserver — no static national file on "
            "environment.data.gov.uk (data.gov.uk only links out to the FC ArcGIS Hub, whose "
            "async exports are not a stable static URL). Now fast anyway: the per-AOI "
            "make_valid(method='structure') on invalid-only geoms (Brief 16) + the load-once "
            "supplementary context (Brief 17 A4) removed the per-tile hang. "
            "If a stable Hub/REST bulk URL is later confirmed, add bulk_url + flip to bulk_download."
        ),
    },
    {
        "name": "WWNP Wider Catchment Woodland Potential",
        "category": "opportunity",
        "nbs_types": ["woodland_planting"],
        "description": "Areas of opportunity for wider catchment woodland planting",
        "access_method": "wfs_direct",
        "coverage": "england",
        "wfs_url": "https://environment.data.gov.uk/spatialdata/wwnp-wider-catchment-woodland-potential/wfs",
        "wfs_layer": "dataset-7b6c23f0-200e-453d-b3f9-1ace36974bce:WWNP_Wider_Catchment_Woodland_Potential",
        "dataset_id": "7b6c23f0-200e-453d-b3f9-1ace36974bce",
        "notes": None,
    },

    # ------------------------------------------------------------------ #
    # CONSTRAINTS DATA                                                     #
    # ------------------------------------------------------------------ #
    {
        "name": "CEH Land Cover Map 2023 Polygon",
        "category": "multi",
        "nbs_types": ["all"],
        "description": (
            "UKCEH Land Cover Map 2023 vector (polygon) edition — used to derive one "
            "constraint mask and one supplementary baseline-land-use layer"
        ),
        "access_method": "local_file",
        "coverage": "gb",
        "source_url": "https://www.ceh.ac.uk/data/ukceh-land-cover-maps",
        "file_path": "data/raw/ceh_landcover_2023/ceh_landcover_parcel_2023.gpkg",
        "file_layer": "defra_ceh_land_cover_map_2023",
        "primary_attribute": "mode",
        "notes": (
            "522 MB GeoPackage (1,237,344 Polygons, EPSG:27700) converted in QGIS "
            "from the original 1.16 GB GeoJSON delivered via the DEFRA Data Service "
            "Platform (DSP) order route — bypasses the EIDC click-through entirely. "
            "Layer name 'defra_ceh_land_cover_map_2023'. Attributes: fid, gid, hist, "
            "mode (primary attribute), agg, purity, conf, stdev, n. Class codes match "
            "the published UKCEH LCM legend (stable across 2017–2023 releases) — "
            "mode in (20, 21, 11, 1) verified as the correct filter for urban / "
            "suburban / bog / broadleaved-woodland. Constraint filter excludes "
            "coniferous woodland (class 2) by design — see "
            "docs/methodology/02_architecture_vector_only.md. AOI clipping is still "
            "advisable as a one-off preprocess step for performance, but the format "
            "conversion that was previously a blocker is now done."
        ),
        "derived_uses": [
            {
                "use": "constraint",
                "name": "CEH Constraint Mask",
                "category": "constraint",
                "filter": "mode in (20, 21, 11, 1)",
                "rationale": (
                    "Excludes existing high-value or construction-incompatible land cover: "
                    "urban (20), suburban (21), bog/peat (11), broadleaved woodland (1). "
                    "Coniferous woodland (2) excluded by design — treated as a woodland "
                    "planting opportunity, not a constraint."
                ),
                "nbs_types": ["all"],
            },
            {
                "use": "supplementary",
                "name": "Baseline Land Use",
                "category": "supplementary",
                "filter": None,
                "scoring_attribute": "mode",
                "rationale": (
                    "All polygons retained; CEH_LU class joined to opportunity polygons as "
                    "a priority-scoring attribute (arable and improved grassland score higher "
                    "as land-use change candidates)."
                ),
                "nbs_types": ["all"],
            },
        ],
    },
    {
        "name": "OS Zoomstack Roads",
        "category": "constraint",
        "nbs_types": ["all"],
        "description": "Road network — 10 m buffer applied as construction constraint",
        "access_method": "local_file",
        "coverage": "gb",
        "source_url": "https://www.ordnancesurvey.co.uk/products/os-open-zoomstack",
        "file_path": "data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg",
        "file_layer": "roads_local",
        "notes": (
            "OS Open Zoomstack (OGL). Roads are split across THREE layers in the "
            "GeoPackage: 'roads_local' (3.26M features — Minor roads), "
            "'roads_regional' (348k features — A / B roads), 'roads_national' "
            "(123k features — Primary / Motorway). For the 10 m road-buffer constraint, "
            "the preprocess step must concatenate all three before buffering. "
            "Roads / Railways / Waterlines share the same ~12 GB Zoomstack download. "
            "Phase 1.5 TODO: OS Data Hub Features API."
        ),
    },
    {
        "name": "OS Zoomstack Railways",
        "category": "constraint",
        "nbs_types": ["all"],
        "description": "Railway network — 20 m buffer applied as construction constraint",
        "access_method": "local_file",
        "coverage": "gb",
        "source_url": "https://www.ordnancesurvey.co.uk/products/os-open-zoomstack",
        "file_path": "data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg",
        "file_layer": "rail",
        "notes": (
            "Same Zoomstack download as Roads / Waterlines. Single 'rail' layer "
            "(115,483 LineStrings, EPSG:27700). 'type' field has values such as "
            "'Narrow Gauge'. Phase 1.5 TODO: OS Data Hub Features API."
        ),
    },
    {
        "name": "OS Zoomstack Surface Water",
        "category": "constraint",
        "nbs_types": ["all"],
        "description": "OS Open Zoomstack surface water polygons — dissolved as surface-water construction constraint",
        "access_method": "local_file",
        "coverage": "gb",
        "source_url": "https://www.ordnancesurvey.co.uk/products/os-open-zoomstack",
        "file_path": "data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg",
        "file_layer": "surfacewater",
        "notes": (
            "Same Zoomstack download as Roads / Railways / Waterlines. "
            "Polygon geometry. Used in the constraints layer (build_constraints_layer) "
            "— dissolved and unioned with roads, rail, CEH LCM mask, and SPZ. "
            "Not given a buffer; surface water polygons used as-is."
        ),
    },
    {
        "name": "Source Protection Zones (No Infiltration Area)",
        "category": "constraint",
        "nbs_types": ["all"],
        "description": "Drinking water catchment protection zones 1 and 2 — infiltration-based NbS excluded",
        "access_method": "wfs_direct",
        "coverage": "england",
        "wfs_url": "https://environment.data.gov.uk/spatialdata/source-protection-zones-merged/wfs",
        "wfs_layer": "dataset-6fd0120f-d465-11e4-abee-f0def148f590:Source_Protection_Zones_Merged",
        "notes": None,
    },
    {
        "name": "WWNP Woodland Constraints",
        "category": "constraint",
        "nbs_types": ["leaky_barriers", "woodland_planting"],
        "description": "Pre-built constraint layer for woodland-related NbS interventions",
        "access_method": "wfs_direct",
        "coverage": "england",
        "wfs_url": "https://environment.data.gov.uk/spatialdata/wwnp-woodland-constraints/wfs",
        "wfs_layer": "dataset-3a6edfe8-3d34-474e-ae35-397fd1f03541:WWNP_Woodland_Constraints",
        "notes": None,
    },

    # ------------------------------------------------------------------ #
    # SUPPLEMENTARY DATA                                                   #
    # ------------------------------------------------------------------ #
    {
        "name": "WFD River Waterbody Catchments Cycle 2 (England)",
        "category": "supplementary",
        "nbs_types": ["all"],
        "description": "EA WFD River Waterbody Catchment polygons (WB_ID-keyed) — used to join WB_ID, WB_NAME, OPCAT_NAME to opportunity polygons. Same provenance as the R model's WBs_Avon.shp.",
        "access_method": "wfs_direct",
        "coverage": "england",
        "wfs_url": "https://environment.data.gov.uk/spatialdata/wfd-river-waterbody-catchments-cycle-2/wfs",
        "wfs_layer": "dataset-7846354f-d465-11e4-89d9-f0def148f590:WFD_River_Water_Body_Catchments_Cycle_2",
        "dataset_id": "7846354f-d465-11e4-89d9-f0def148f590",
        "notes": (
            "WFS VERIFIED working 2026-06-11 via GetFeature (numberMatched=4092 nationally; "
            "native CRS EPSG:27700) — confirms full England coverage, not Avon-only. "
            "Live WFS returns LOWERCASE columns: wb_id, wb_name, rbd_id, rbd_name, wb_cat, "
            "area_m2, length_m (geometry_name='shape'). It does NOT carry OPCAT_NAME. "
            "supplementary.py normalises wb_id/wb_name -> WB_ID/WB_NAME and fills missing "
            "OPCAT_NAME with null. OPCAT_NAME is label-only (excluded from tot_prio), so it is "
            "left null on the full-STW path by decision (2026-06-11) rather than sourced via a "
            "separate Operational Catchments join. "
            "Polygon *catchments* dataset (NOT 'WFD River Water Bodies', which is river centrelines). "
            "Cycle 2 chosen to match the R model provenance; Cycle 3 (current RBMP) is a trivial swap. "
            "Dev/parity fallback: data/reference/R_Model/Supplementary_Data/WBs_Avon.shp (UPPERCASE "
            "WB_ID/WB_NAME/OPCAT_NAME) is used automatically when load_layer() is called in dev-AOI mode. "
            "Note: some boundary-sliver features have blank wb_id/wb_name; _sjoin_largest assigns by "
            "largest overlap so this is low-risk, but spot-check populated WB_ID on first full fetch. "
            "Bulk alternatives on the same DSP page: OGC API Features, and gpkg/shp/geojson .zip downloads."
        ),
    },
    {
        "name": "Agricultural Land Classification (ALC)",
        "category": "supplementary",
        "nbs_types": ["all"],
        "description": "Provisional Agricultural Land Classification grades (national) — high grade reduces NbS suitability score",
        "access_method": "ogc_api",   # Brief 22: PROVISIONAL ALC (national) via OGC API Features
        "coverage": "england",
        # PROVISIONAL ALC (England) — Natural England, digitised 1:250,000, NATIONAL coverage.
        # Switched from the Post-1988 Survey product in Brief 22 (2026-07-28, Jack approved): the
        # Post-1988 survey is a sparse patchwork (~1.9% of STW area, 0% on upland peat) that left
        # alc_grade null across most of the AOI; Provisional is national and matches the R model
        # (data/reference/.../Agricultural_Land_Classification_Provisional_EnglandPolygon.shp).
        # Field 'alc_grade' with single Grade 1-5 (NO 3a/3b subdivision) — matches R + the score
        # table. Verified 2026-07-28: OGC numberMatched national=1,826 (coarse product, large
        # polygons), 836 over the STW bbox, non-null in North Notts where Post-1988 was null.
        "ogc_url": "https://environment.data.gov.uk/geoservices/datasets/af1b847b-037b-4772-9c31-7edf584522aa/ogc/features/v1",
        "ogc_collection": "Agricultural_Land_Classification_Provisional_England",
        "wfs_url": "https://environment.data.gov.uk/spatialdata/agricultural-land-classification-provisional-england/wfs",
        "dataset_id": "af1b847b-037b-4772-9c31-7edf584522aa",
        # DORMANT — the former Post-1988 Survey source (grades 3a/3b, PARTIAL coverage). Kept for
        # provenance; do NOT use (sparse patchwork — the reason for the Brief 22 switch).
        "_post1988_ogc_url": "https://environment.data.gov.uk/geoservices/datasets/492f5119-3c59-4798-a3a0-3bc4ca589aec/ogc/features/v1",
        "_post1988_bulk_url": "https://environment.data.gov.uk/api/file/download?fileDataSetId=fcb11d52-2cc9-4930-b8a7-8b07c2154407&fileName=Agricultural_Land_Classification_ALC_Grades_Post_1988_Survey_polygons.gpkg.zip",
        "notes": (
            "PROVISIONAL ALC via OGC API Features (Brief 22, 2026-07-28). National coverage, "
            "single Grade 1-5 (matches R + the alc_grade score table). Replaced the Post-1988 "
            "Survey bulk product, whose DSP export was a sparse patchwork leaving alc_grade null "
            "across most of STW (2026-07-03 review C2). Coarse 1:250k product — few large "
            "polygons (national numberMatched=1,826), so the per-tile OGC fetch is light."
        ),
    },
    {
        "name": "Priority Habitat Area (Habitat Networks)",
        "category": "supplementary",
        "nbs_types": ["all"],
        "description": "Natural England Habitat Networks Combined — presence increases NbS priority score",
        "access_method": "bulk_download",   # Brief 17: national gpkg downloaded once, clipped per AOI
        "coverage": "england",
        # ogc_url/ogc_collection retained as a dormant fallback (the OGC route still works):
        "ogc_url": "https://environment.data.gov.uk/geoservices/datasets/5e614b67-ccd0-4673-8ad8-adddf538125e/ogc/features/v1",
        "ogc_collection": "Habitat_Networks_Combined_Habitats_England",
        # Bulk national GeoPackage (Brief 17): download once, validate once, clip per AOI.
        "bulk_url": "https://environment.data.gov.uk/api/file/download?fileDataSetId=a151421a-1a41-44ad-a20a-ff4bcf265cad&fileName=Habitat_Networks_England.gpkg.zip",
        # Retained for provenance / manual WFS fallback (not used while access_method=ogc_api):
        "wfs_url": "https://environment.data.gov.uk/spatialdata/habitat-networks-combined-habitats-england/wfs",
        "wfs_layer": "dataset-5e614b67-ccd0-4673-8ad8-adddf538125e:Habitat_Networks_Combined_Habitats_England",
        "dataset_id": "626d5050-7f3e-48ed-a68f-8b8e90d02a3e",
        "notes": "Migrated to OGC API Features 2026-06-15 (Brief 11) — dense (numberMatched=31332 over the dev AOI); WFS GML truncated.",
    },
    {
        "name": "Soil Parent Material Model (1 km generalised)",
        "category": "supplementary",
        "nbs_types": ["all"],
        "description": "BGS soil texture/type — ranked from heavy (clay) to light (sand) as infiltration proxy",
        "access_method": "local_file",
        "coverage": "gb",
        "source_url": "https://www.bgs.ac.uk/datasets/soil-parent-material-model/",
        "file_path": "data/raw/bgs_soil_parent_material_1km/SoilParentMateriall_V1_portal1km.shp",
        "version": "DPSPM_V1_1km",
        "notes": (
            "BGS open data. 241,514 polygons, EPSG:27700. Shapefile (note the BGS "
            "filename has a typo: 'Materiall' with two L's — keep as supplied). "
            "This is the BGS 1 km GENERALISED product, not the full-resolution "
            "50 m version. Adequate for catchment-scale priority scoring and "
            "dramatically faster to process; use full-res only if a Phase 1.5 "
            "request from Matt makes it relevant. Key attributes for "
            "infiltration-proxy scoring: SOIL_GROUP (LIGHT(SANDY) / MEDIUM / HEAVY), "
            "SOIL_TEX, PMM_GRAIN (COARSE / MEDIUM / FINE), ESB_DESC (parent material), "
            "SOIL_DEPTH. Phase 1.5 TODO: test BGS WFS at ogc.bgs.ac.uk for "
            "programmatic access."
        ),
    },
    {
        "name": "EA NbS Infiltration Class",
        "category": "supplementary",
        "nbs_types": ["all"],
        "description": "1–5 score of land's ability to infiltrate water (EA internal dataset)",
        "access_method": "manual_download",
        "coverage": "england",
        "source_url": "https://environment.maps.arcgis.com/apps/webappviewer/index.html?id=91202d8f6e3947689dc1c74b9fdd078f",
        "notes": (
            "ArcGIS web app only; underlying REST service not publicly documented. "
            "Severn Trent do NOT hold this dataset — must be requested directly from the EA. "
            "BGS Groundwater Vulnerability Map is the licensed substitute, pending confirmation "
            "of commercial-use terms. Phase 1.5 TODO: raise formal EA data request."
        ),
    },
    {
        "name": "Recharge Prioritisation (HML)",
        "category": "supplementary",
        "nbs_types": ["all"],
        "description": (
            "Natural England waterbody-scale prioritisation of groundwater recharge "
            "(High/Medium/Low). Used in Phase 1 as a standalone supplementary scoring "
            "signal. NOTE: this is NOT an infiltration-capacity or infiltration-"
            "potential measure — it scores the relative importance of each WFD "
            "waterbody for groundwater recharge protection / enhancement."
        ),
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/Recharge_Potential_Detailed_HML/FeatureServer",
        "layer_index": 2,
        "layer_name": "Recharge_Potential_Detailed_HML",
        "max_record_count": 2000,
        "notes": (
            "Primary attribute: PRIORITISATION (HIGH | MEDIUM | LOW). "
            "Additional attributes: EA_WB_ID, WATERBODY_NAME. "
            "Distinct from the EA Recharge Potential layer (1–5 CUMULATIVE field at "
            "soil-polygon scale) used in the original R model — that remains pending "
            "direct EA request. Use this as a waterbody-scale scoring signal."
        ),
    },

    # ------------------------------------------------------------------ #
    # EXPERIMENTAL — PEAT RESTORATION NbS                                 #
    # All entries below carry experimental=True and are gated by          #
    # INCLUDE_EXPERIMENTAL. Awaiting stakeholder go/no-go from            #
    # Matt Palmer (Severn Trent) before activation for client delivery.   #
    # ------------------------------------------------------------------ #
    {
        "name": "England Peat Map — Peaty Soil Extent",
        "category": "opportunity",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "description": "Spatial extent of peaty soils in England — gating layer for all peat restoration steps",
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/peaty_soil_extent_v1/FeatureServer",
        "layer_index": 0,
        "layer_name": "peaty_soil_extent_v1",
        "max_record_count": 2000,
        "notes": "Natural England / AI4Peat hub. OGL v3. Use as gating mask — restrict all peat restoration steps to features within this extent.",
    },
    {
        "name": "England Peat Map — Peaty Soil Depth",
        "category": "opportunity",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "description": "10 m raster of predicted peat depth (cm) — used to identify 'true peat' >= 40 cm threshold per NERR149",
        "access_method": "arcgis_static_download",
        "coverage": "england",
        "download_url": "https://www.arcgis.com/sharing/rest/content/items/bc4527cbbc0c4acc92b44e85528c975e/data",
        "item_id": "bc4527cbbc0c4acc92b44e85528c975e",
        "file_format": "geotiff",
        "size_mb": 475,
        "notes": (
            "OGL v3. England-wide 10 m raster. "
            "Pre-processing: scripts/preprocess_peat_depth.py -- download once, clip to STW AOI, "
            "compute polygon-level zonal stats (mean depth) against Peaty Soil Extent vector, "
            "write enriched vector with peat_depth_cm_mean attribute. "
            "Pipeline modules consume the enriched vector only -- no raster in src/."
        ),
    },
    {
        "name": "England Peat Map — Peaty Soil Depth Confidence",
        "category": "opportunity",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "description": "10 m RMSE raster paired with depth — used to filter to medium/high confidence predictions",
        "access_method": "arcgis_static_download",
        "coverage": "england",
        "download_url": "https://www.arcgis.com/sharing/rest/content/items/edb3acca28db43c99af414062ad3c928/data",
        "item_id": "edb3acca28db43c99af414062ad3c928",
        "file_format": "geotiff",
        "size_mb": None,
        "notes": (
            "Sibling raster to Peaty Soil Depth on same ArcGIS Online org. "
            "Same pre-processing pattern as Depth: extend scripts/preprocess_peat_depth.py "
            "to also compute mean confidence (peat_depth_confidence_rmse_mean) per polygon."
        ),
    },
    {
        "name": "England Peat Map — Bare Peaty Soil",
        "category": "opportunity",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "description": "Mapped bare peat areas — degradation signal for Step 2",
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/England_Peat_Map_Upland_Peat_Erosion_and_Drainage_Bare_Peat/FeatureServer",
        "layer_index": None,
        "layer_name": "Upland Peat Erosion and Drainage Bare Peat (by BGZ)",
        "max_record_count": 2000,
        "bgz_tiled": True,
        "bgz_layer_ids": [1, 2, 3, 4, 5, 6, 11, 13],
        "notes": (
            "Service is tiled by Biogeographical Zone (BGZ). "
            "Query all BGZ layers and concatenate results for national coverage. "
            "BGZ layer IDs confirmed: 1,2,3,4,5,6,11,13."
        ),
    },
    {
        "name": "England Peat Map — Upland Grips",
        "category": "opportunity",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "pipeline_wired": True,   # one of the two signals peat_restoration actually loads (Brief 19)
        "description": "Mapped grip (artificial drainage ditch) network on peaty soils — peat opportunity signal (buffered)",
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/England_Peat_Map_Upland_Peat_Erosion_and_Drainage_Grips/FeatureServer",
        "layer_index": 1,
        "layer_name": "Upland Peat Erosion and Drainage Grips",
        "max_record_count": 2000,
        "notes": "Grips are drainage ditches cut into peat -- their presence indicates artificial drainage requiring restoration.",
    },
    {
        "name": "England Peat Map — Upland Gullies",
        "category": "opportunity",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "pipeline_wired": True,   # one of the two signals peat_restoration actually loads (Brief 19)
        "description": "Mapped peat gullies — erosion feature, peat opportunity signal (buffered)",
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/England_Peat_Map_Upland_Peat_Erosion_and_Drainage_Gullies/FeatureServer",
        "layer_index": 1,
        "layer_name": "Upland Peat Erosion and Drainage Gullies",
        "max_record_count": 2000,
        "notes": None,
    },
    {
        "name": "England Peat Map — Upland Haggs",
        "category": "opportunity",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "description": "Mapped peat haggs (eroded peat cliffs/blocks) — erosion feature, degradation signal for Step 2",
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/England_Peat_Map_Upland_Peat_Erosion_and_Drainage_Haggs/FeatureServer",
        "layer_index": 1,
        "layer_name": "Upland Peat Erosion and Drainage Haggs",
        "max_record_count": 2000,
        "notes": None,
    },
    {
        "name": "England Peat Map — Vegetation and Land Cover on Peaty Soils",
        "category": "opportunity",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "description": (
            "Vegetation and land cover classes on peaty soils -- drives both Step 2 "
            "(include dry-peat / agricultural vegetation) and Step 3 exclusion "
            "(exclude intact wet bog / sphagnum-dominated vegetation)"
        ),
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/England_Peat_Map_Vegetation_and_Land_Cover_on_Peaty_Soils/FeatureServer",
        "layer_index": None,
        "layer_name": "EPM Vegetation and Land Cover (by BGZ)",
        "max_record_count": 2000,
        "bgz_tiled": True,
        "bgz_layer_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
        "notes": (
            "Service is tiled by Biogeographical Zone (BGZ) -- query all 14 layers and "
            "concatenate for national coverage. "
            "Same single layer drives two pipeline roles via derived_uses. "
            "TODO: define DRY_PEAT_VEG_CLASSES (heather-dominated, agricultural use) "
            "and WET_BOG_VEG_CLASSES (sphagnum-dominated, intact blanket bog) from "
            "Natural England's vegetation classification scheme."
        ),
        "derived_uses": [
            {
                "use": "step2_dry_degraded_inclusion",
                "name": "Dry/Degraded Vegetation (include)",
                "category": "opportunity",
                "filter": "veg_class in DRY_PEAT_VEG_CLASSES",
                "rationale": "Heather-dominated and agricultural land-cover classes indicate degraded dry peat that can benefit from restoration.",
                "nbs_types": ["peat_restoration"],
            },
            {
                "use": "step3_wet_bog_exclusion",
                "name": "Intact Wet Bog (exclude)",
                "category": "opportunity",
                "filter": "veg_class in WET_BOG_VEG_CLASSES",
                "rationale": "Sphagnum-dominated and intact blanket bog signatures indicate near-natural peat -- avoid disturbing these areas.",
                "nbs_types": ["peat_restoration"],
            },
        ],
    },
    {
        "name": "England Peat Map — Status, GHG and Carbon Storage",
        "category": "supplementary",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "description": "Peat condition, greenhouse gas emissions, and carbon stock estimates — Peatland Code-aligned supplementary scoring",
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/England_Peat_Status_GHG_and_C_Storage/FeatureServer",
        "layer_index": 0,
        "layer_name": "England Peat Status GHG and C storage -- BGS & NSRI",
        "max_record_count": 1000,
        "notes": (
            "Also available at environment.data.gov.uk/arcgis/rest/services/NE/"
            "EnglandPeatStatusGreenhouseGasandCarbonStorage/FeatureServer -- same data, "
            "two hosting locations. Use NE hub URL for consistency. "
            "Feeds Peatland Code-aligned carbon-credit scoring; downstream scoring logic "
            "is out of scope for Phase 1."
        ),
    },
    {
        "name": "England Peat Map — Grip Dams",
        "category": "supplementary",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "description": "Mapped grip dam installations (reference data; not used in pipeline rules)",
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/England_Peat_Map_Upland_Peat_Erosion_and_Drainage_Grip_Dams/FeatureServer",
        "layer_index": 1,
        "layer_name": "Upland Peat Erosion and Drainage Grip Dams",
        "max_record_count": 2000,
        "notes": (
            "Grip dams are dams installed in drainage grips to block drainage and re-wet peat. "
            "Retained as a reference/contextual layer -- useful for mapping active restoration "
            "activity in the STW area but not encoded as a pipeline exclusion rule. "
            "Layer index 1 (not 0) -- confirmed by service directory listing."
        ),
    },
    {
        "name": "Moorland Deep Peat Action Programme Status (England)",
        "category": "supplementary",
        "nbs_types": ["peat_restoration"],
        "experimental": True,
        "description": "Defra Action Programme areas for deep peat (reference data; not used in pipeline rules)",
        "access_method": "arcgis_featureserver",
        "coverage": "england",
        "service_url": f"{_NE_HUB}/Moorland_Deep_Peat_AP_Status_England/FeatureServer",
        "layer_index": 0,
        "layer_name": "Moorland Deep Peat AP Status (England) -- BGS & NSRI",
        "max_record_count": 1000,
        "notes": (
            "Formal programme boundary layer -- useful for contextual reporting on "
            "how much of the STW peat restoration opportunity overlaps with Defra "
            "programme areas. Retained as reference data, not a pipeline exclusion."
        ),
    },
]

# ---------------------------------------------------------------------------
# Peat restoration methodology rules (Step 1-3 filter structure)
# ---------------------------------------------------------------------------
# This encodes the three-step methodology for capture and validation.
# Actual filter execution is downstream pipeline work (not Phase 1).
# TODO items require Natural England classification scheme review.

PEAT_RESTORATION_RULES = {
    "step_1_restorable_peat": {
        "description": "Identify peat that is restorable (true peat, confident prediction).",
        "logic": "AND",
        "filters": [
            {
                "layer": "england-peat-map-peaty-soil-extent",
                "predicate": "presence",
                "note": "Gating mask -- all steps restricted to features within this extent.",
            },
            {
                "layer": "england-peat-map-peaty-soil-depth",
                "predicate": "peat_depth_cm_mean >= 40",
                "unit": "cm",
                "note": "Natural England NERR149 'true peat' threshold for restoration planning.",
            },
            {
                "layer": "england-peat-map-peaty-soil-depth-confidence",
                "predicate": "peat_depth_confidence_rmse_mean in ('medium', 'high')",
                "note": "TODO: confirm Natural England's confidence-class encoding from documentation.",
            },
        ],
        "rationale": "Natural England NERR149 'true peat' threshold for action planning.",
        "source": "Natural England NERR149",
    },
    "step_2_degradation_signals": {
        "description": "Flag areas with active or visible degradation.",
        "logic": "OR",
        "filters": [
            {
                "layer": "england-peat-map-bare-peaty-soil",
                "predicate": "presence",
            },
            {
                "layer": "england-peat-map-upland-grips",
                "predicate": "presence",
            },
            {
                "layer": "england-peat-map-upland-gullies",
                "predicate": "presence",
            },
            {
                "layer": "england-peat-map-upland-haggs",
                "predicate": "presence",
            },
            {
                "layer": "england-peat-map-vegetation",
                "predicate": "veg_class in DRY_PEAT_VEG_CLASSES",
                "note": (
                    "Class set resolved 2026-06-04 — see "
                    "docs/methodology/03_peat_restoration_experimental.md "
                    "section 'Vegetation Classification'. Definitions based on "
                    "NERR149 principles (sphagnum-absent ericoid / agricultural "
                    "cover on peaty soils is degraded). Actual veg_class attribute "
                    "values to be confirmed at first fetch of the EPM Vegetation "
                    "and Land Cover layer."
                ),
            },
        ],
        "rationale": "Nationally recognised degradation indicators per Natural England England Peat Map.",
    },
    "step_3_exclude_intact": {
        "description": (
            "Remove areas already in good condition. "
            "Active-restoration overlap is deliberately not encoded as an exclusion -- "
            "sites adjacent to existing restoration can be valid additional opportunities."
        ),
        "logic": "AND_NOT",
        "filters": [
            {
                "layer": "england-peat-map-vegetation",
                "predicate": "veg_class in WET_BOG_VEG_CLASSES",
                "note": (
                    "Class set resolved 2026-06-04 -- see "
                    "docs/methodology/03_peat_restoration_experimental.md "
                    "section 'Vegetation Classification'. Definitions based on "
                    "NERR149 principles (sphagnum-dominated, active blanket / "
                    "raised bog signatures are intact and must be excluded from "
                    "the restoration-opportunity set). Actual veg_class attribute "
                    "values to be confirmed at first fetch of the EPM Vegetation "
                    "and Land Cover layer."
                ),
            },
        ],
        "rationale": (
            "Avoid disturbing near-natural peat that does not need intervention. "
            "Grip dams and Deep Peat AP Status are retained as reference/contextual layers "
            "but are not encoded as exclusion rules -- areas adjacent to active restoration "
            "can be valid additional opportunities."
        ),
    },
}
