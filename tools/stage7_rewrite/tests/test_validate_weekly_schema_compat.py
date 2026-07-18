import importlib.util
import json
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_weekly_schema_compat.py"
spec = importlib.util.spec_from_file_location("validate_weekly_schema_compat", SCRIPT)
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def write_minimal_registry_schema_set(schemas: Path, registries: Path):
    fixtures = [
        (
            "weekly_account_registry.v1.schema.json",
            "weekly_accounts_seed.json",
            "accounts",
            {"account_id": "dada", "account_name": "Dada Bar Beijing", "aliases": []},
        ),
        (
            "weekly_artist_registry.v1.schema.json",
            "weekly_artists_seed.json",
            "artists",
            {"artist_id": "fat-k", "canonical_name": "Fat-K", "aliases": []},
        ),
        (
            "weekly_venue_registry.v1.schema.json",
            "weekly_venues_seed.json",
            "venues",
            {"venue_id": "dada-beijing", "canonical_name": "Dada Beijing", "aliases": []},
        ),
    ]
    for schema_name, registry_name, collection, row in fixtures:
        write_json(
            schemas / schema_name,
            {
                "type": "object",
                "required": [collection],
                "properties": {collection: {"type": "array"}},
            },
        )
        write_json(registries / registry_name, {collection: [row]})


def test_current_registry_seeds_match_restored_schemas():
    for schema_name, registry_name in compat.REGISTRY_BY_SCHEMA.items():
        schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "registries" / registry_name).read_text(encoding="utf-8"))

        issues = compat.validate_value(registry, schema, registry_name)

        assert issues == [], f"{registry_name}: {issues[:5]}"


def test_validate_value_reports_required_const_and_type_errors():
    schema = {
        "type": "object",
        "required": ["schema_version", "name", "count"],
        "properties": {
            "schema_version": {"const": "demo.v1"},
            "name": {"type": "string", "minLength": 1},
            "count": {"type": "integer", "minimum": 1},
        },
    }

    issues = compat.validate_value({"schema_version": "bad", "name": "", "count": 0}, schema, "item")

    messages = [issue["message"] for issue in issues]
    assert "must equal 'demo.v1'" in messages
    assert "length below minLength 1" in messages
    assert "below minimum 1" in messages


def test_event_release_pack_direct_check_requires_adapter(tmp_path):
    release_pack = tmp_path / "pack"
    write_jsonl(
        release_pack / "events.jsonl",
        [
            {
                "schema_version": "stage7_consumer_release_pack.v1",
                "card_type": "event",
                "evid": "e1",
                "name": "Party",
                "confidence": 0.95,
                "source_article_uid": "acct/a1",
            }
        ],
    )
    schema = {
        "type": "object",
        "not": {"anyOf": [{"required": ["confidence"]}]},
        "required": ["schema_version", "event_id", "title_display"],
        "properties": {
            "schema_version": {"const": "weekly_event_published.v1"},
            "event_id": {"type": "string"},
            "title_display": {"type": "string"},
        },
    }

    result = compat.validate_event_schema_against_pack(schema, release_pack, sample_per_file=10)

    assert result["ok"] is False
    assert result["decision"] == "adapter_required_before_weekly_publish"
    assert "event_id" in result["field_coverage"]["missing_all"]
    assert result["issues"]["issue_count"] > 0


def test_registry_schema_coverage_matches_aliases(tmp_path):
    schemas = tmp_path / "schemas"
    registries = tmp_path / "registries"
    release_pack = tmp_path / "pack"
    write_jsonl(release_pack / "articles.jsonl", [{"source_account": "Dada Bar Beijing"}])
    write_jsonl(release_pack / "events.jsonl", [{"place": "Dada Beijing", "participants": ["Fat-K"], "organizers": []}])

    schema = {
        "type": "object",
        "required": ["schema_version", "updated_at", "venues"],
        "properties": {
            "schema_version": {"const": "weekly_venue_registry.v1"},
            "updated_at": {"type": "string"},
            "venues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["venue_id", "canonical_name", "aliases"],
                    "properties": {
                        "venue_id": {"type": "string"},
                        "canonical_name": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }
    schema_path = schemas / "weekly_venue_registry.v1.schema.json"
    write_json(schema_path, schema)
    write_json(
        registries / "weekly_venues_seed.json",
        {
            "schema_version": "weekly_venue_registry.v1",
            "updated_at": "2026-05-15",
            "venues": [{"venue_id": "dada", "canonical_name": "Dada Beijing", "aliases": ["Dada Bar Beijing"]}],
        },
    )
    release_names = compat.collect_release_names(release_pack, coverage_limit=0)

    result = compat.validate_registry_schema(schema_path, schema, registries, release_names)

    assert result["ok"] is True
    assert result["coverage"]["matched_unique"] == 1
    assert result["decision"] == "registry_schema_and_sample_coverage_ready"


def test_selected_weekly_path_unblocks_direct_stage7_schema_adapter_gap(tmp_path):
    schemas = tmp_path / "schemas"
    registries = tmp_path / "registries"
    release_pack = tmp_path / "pack"
    weekly_path_report = tmp_path / "weekly_path.json"
    write_jsonl(release_pack / "articles.jsonl", [{"source_account": "Dada Bar Beijing"}])
    write_jsonl(
        release_pack / "events.jsonl",
        [
            {
                "schema_version": "stage7_consumer_release_pack.v1",
                "card_type": "event",
                "evid": "e1",
                "name": "Party",
                "confidence": 0.95,
                "place": "Dada Beijing",
                "participants": ["Fat-K"],
                "organizers": [],
            }
        ],
    )
    write_minimal_registry_schema_set(schemas, registries)
    write_json(
        schemas / "weekly_event_published.v1.schema.json",
        {
            "type": "object",
            "not": {"anyOf": [{"required": ["confidence"]}]},
            "required": ["schema_version", "event_id", "title_display"],
            "properties": {
                "schema_version": {"const": "weekly_event_published.v1"},
                "event_id": {"type": "string"},
                "title_display": {"type": "string"},
            },
        },
    )
    write_json(
        weekly_path_report,
        {
            "ok": True,
            "production_ready": True,
            "decision": "weekly_publish_path_selected_production_ready",
            "recommended_path": "weekly_recommendation_pipeline_for_weekly_publish",
        },
    )

    report = compat.build_report(
        Namespace(
            release_pack=release_pack,
            schemas=schemas,
            registries=registries,
            out_dir=tmp_path / "out",
            sample_per_file=10,
            coverage_limit=0,
            weekly_path_report=weekly_path_report,
            allow_selected_weekly_path=True,
            report_only_exit_zero=True,
        )
    )

    assert report["ok"] is True
    assert report["blockers"] == []
    assert report["decision"] == "weekly_schema_selected_path_ready_direct_stage7_adapter_deferred"
    assert report["selected_weekly_path"]["direct_stage7_schema_blocked_but_not_selected"] is True


def test_unexpected_schema_blocks_otherwise_ready_selected_path(tmp_path):
    schemas = tmp_path / "schemas"
    registries = tmp_path / "registries"
    release_pack = tmp_path / "pack"
    weekly_path_report = tmp_path / "weekly_path.json"
    write_jsonl(release_pack / "articles.jsonl", [{"source_account": "Dada Bar Beijing"}])
    write_jsonl(
        release_pack / "events.jsonl",
        [
            {
                "schema_version": "stage7_consumer_release_pack.v1",
                "confidence": 0.95,
                "place": "Dada Beijing",
                "participants": ["Fat-K"],
                "organizers": [],
            }
        ],
    )
    write_minimal_registry_schema_set(schemas, registries)
    write_json(
        schemas / "weekly_event_published.v1.schema.json",
        {
            "type": "object",
            "not": {"anyOf": [{"required": ["confidence"]}]},
            "required": ["schema_version", "event_id"],
        },
    )
    write_json(schemas / "weekly_unknown.v1.schema.json", {"type": "object"})
    write_json(
        weekly_path_report,
        {
            "ok": True,
            "production_ready": True,
            "recommended_path": "weekly_recommendation_pipeline_for_weekly_publish",
        },
    )

    report = compat.build_report(
        Namespace(
            release_pack=release_pack,
            schemas=schemas,
            registries=registries,
            out_dir=tmp_path / "out",
            sample_per_file=10,
            coverage_limit=0,
            weekly_path_report=weekly_path_report,
            allow_selected_weekly_path=True,
            report_only_exit_zero=True,
        )
    )

    assert report["ok"] is False
    assert report["decision"] == "weekly_schema_set_missing_or_unexpected"
    assert report["schema_set"]["unexpected"] == ["weekly_unknown.v1.schema.json"]
