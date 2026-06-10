param(
  [string]$Root = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite",
  [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $Root

Write-Host "== Stage7 safe handoff verify =="
Write-Host "root=$Root"

Write-Host "`n== Python targeted tests =="
python -m pytest `
  tests\test_validate_maigret_source_hits.py `
  tests\test_run_cdcr_fallback_canary.py `
  tests\test_validate_public_social_links.py `
  tests\test_build_p1_social_graph_acceptance_pack.py `
  tests\test_review_p1_social_graph_candidates.py `
  tests\test_neo4j_p1_social_staging_writer.py `
  tests\test_validate_consumer_publish_gate.py `
  tests\test_build_consumer_production_gate_packet.py `
  tests\test_build_ocr_file_index.py `
  tests\test_build_ocr_canary_queue.py `
  tests\test_build_dajiala_roi_budget_gate_packet.py `
  tests\test_run_maigret_http_canary.py `
  tests\test_recover_maigret_web_container_reports.py `
  tests\test_build_maigret_candidate_list.py `
  tests\test_import_dj_dataset_radio_assets.py `
  tests\test_hermes_heartbeat.py `
  tests\test_hermes_metrics_collector.py `
  tests\test_hermes_alert_manager.py `
  tests\test_hermes_cost_tracker.py `
  tests\test_hermes_dashboard.py `
  tests\test_extract_publish_time_from_content.py `
  tests\test_extract_publish_time_from_html.py `
  tests\test_analyze_article_url_timestamps.py `
  tests\test_consolidate_publish_times.py `
  tests\test_validate_cdcr_direct_sources.py `
  tests\test_extract_radio_social_links.py `
  tests\test_crawl_social_deep_profiles.py `
  tests\test_parse_linktree_urls.py `
  tests\test_build_social_deep_edge_pack.py `
  tests\test_snapshot_qdrant_collections.py `
  tests\test_mem0_dimension_gate.py `
  tests\test_mem0_local_write_read_canary.py `
  tests\test_build_mem0_write_gate_packet.py `
  tests\test_build_dj_collaboration_graph.py `
  tests\test_recommend_graph_similarity.py `
  tests\test_build_trending_index.py `
  tests\test_recommend_hybrid.py `
  tests\test_graph_rag_nl_to_cypher.py `
  tests\test_graph_rag_retrieve.py `
  tests\test_graph_rag_hybrid_context.py `
  tests\test_graph_rag_answer.py `
  tests\test_validate_weekly_schema_compat.py `
  tests\test_run_e2e_integration.py `
  tests\test_build_weekly_event_published_canary.py `
  tests\test_trace_weekly_time_iso_gap.py `
  tests\test_decide_weekly_publish_path.py `
  tests\test_summarize_prd_longrun_status.py `
  tests\test_build_canonical_entities.py `
  tests\test_validate_graph_promotion_readiness.py `
  tests\test_validate_consumer_deploy_readiness.py `
  tests\test_promote_graph_to_production.py `
  tests\test_consumer_query_smoke.py `
  tests\test_extract_ocr_entities.py `
  tests\test_merge_ocr_entities_to_neo4j.py `
  tests\test_audit_ocr_reflow_readiness.py `
  tests\test_extract_ocr_entities_from_sidecar.py `
  tests\test_audit_poster_ocr_text_gate.py `
  tests\test_review_social_identity_cross_evidence.py `
  tests\test_synthesize_ocr_asset_blockers.py `
  tests\test_build_final_full_pipeline_readiness.py `
  tests\test_build_full_pipeline_launch_packet.py `
  tests\test_build_full_pipeline_release_candidate_manifest.py `
  tests\test_build_full_pipeline_production_operation_packet.py `
  tests\test_build_language_field_vector_jobs.py `
  tests\test_build_vector_role_artifacts.py `
  tests\test_run_full_vectorize_endpoint.py `
  tests\test_qdrant_full_staging_writer.py `
  tests\test_stage7_runtime_guard.py `
  tests\test_embed_vector_role_artifact.py `
  tests\test_qdrant_vector_role_staging_writer.py `
  tests\test_run_vector_router_smoke.py `
  tests\test_run_vector_semantic_router_eval.py `
  tests\test_run_vector_role_full_wave.py `
  tests\test_run_vector_collection_router_smoke.py `
  tests\test_qdrant_role_alias_gate.py `
  tests\test_apply_qdrant_role_alias_gate.py `
  tests\test_run_qdrant_role_alias_router_smoke.py `
  tests\test_qdrant_alias_promote.py `
  tests\test_build_graph_rag_recommendation_current_smoke.py `
  tests\test_verify_cloudrun_stage7_packaging.py `
  tests\test_build_cloudrun_deploy_execution_report.py `
  tests\test_smoke_cloudrun_stage7_production.py `
  tests\test_smoke_cloudrun_weekly_production.py `
  tests\test_build_recovered_artifact_manifest.py `
  tests\test_audit_ocr_md_deepseek_contract.py `
  tests\test_build_production_gate_cancellation_packet.py `
  tests\test_build_stage7_integrated_design_execution_plan.py `
  tests\test_build_miniprogram_upload_execution_report.py `
  tests\test_build_miniprogram_review_submission_boundary.py `
  tests\test_build_production_sqlite_surface_decision.py `
  tests\test_build_superlongrun_production_state_packet.py `
  tests\test_reconcile_93k_live_status.py `
  tests\test_build_stage7_data_completeness_gap_ledger.py `
  tests\test_build_v6_p1_existing_ocr_locator.py `
  tests\test_build_v6_p1_ocr_markdown_merge_inputs.py `
  tests\test_run_v6_p1_local_ocr_repair.py `
  tests\test_merge_stable_article_jsonl.py `
  tests\test_build_v6_47k_merge_readiness_packet.py `
  tests\test_build_graph_external_evidence_seed_queue.py `
  tests\test_run_graph_external_evidence_http_fast.py `
  tests\test_build_graph_maigret_candidates_from_seed_queue.py `
  tests\test_build_graph_external_identity_review_queue.py `
  tests\test_adjudicate_graph_external_identity_queue.py `
  tests\test_run_external_identity_source_followup.py `
  tests\test_build_external_identity_source_followup_review_gate.py `
  tests\test_build_graph_candidate_pack_readiness.py `
  tests\test_recover_external_identity_source_context.py `
  tests\test_build_external_identity_source_context_decision_packet.py `
  tests\test_build_atlas_full_source_lineage.py `
  tests\test_build_atlas_gap_backfill_execution_packet.py `
  tests\test_build_wechat_graph_pipeline_code_inventory.py `
  -q

Write-Host "`n== Python compile =="
python -m py_compile `
  scripts\validate_maigret_source_hits.py `
  scripts\run_cdcr_fallback_canary.py `
  scripts\validate_public_social_links.py `
  scripts\build_p1_social_graph_acceptance_pack.py `
  scripts\review_p1_social_graph_candidates.py `
  scripts\neo4j_p1_social_staging_writer.py `
  scripts\validate_consumer_publish_gate.py `
  scripts\build_consumer_production_gate_packet.py `
  scripts\write_consumer_release_pointer.py `
  scripts\build_ocr_file_index.py `
  scripts\build_ocr_canary_queue.py `
  scripts\build_dajiala_roi_budget_gate_packet.py `
  scripts\run_maigret_http_canary.py `
  scripts\build_maigret_candidate_list.py `
  scripts\import_dj_dataset_radio_assets.py `
  scripts\hermes_monitor_common.py `
  scripts\hermes_heartbeat.py `
  scripts\hermes_metrics_collector.py `
  scripts\hermes_alert_manager.py `
  scripts\hermes_cost_tracker.py `
  scripts\hermes_dashboard.py `
  scripts\extract_publish_time_from_content.py `
  scripts\extract_publish_time_from_html.py `
  scripts\analyze_article_url_timestamps.py `
  scripts\consolidate_publish_times.py `
  scripts\validate_cdcr_direct_sources.py `
  scripts\extract_radio_social_links.py `
  scripts\crawl_soundcloud_profiles.py `
  scripts\crawl_bandcamp_profiles.py `
  scripts\parse_linktree_urls.py `
  scripts\build_social_deep_edge_pack.py `
  scripts\snapshot_qdrant_collections.py `
  scripts\mem0_dimension_gate.py `
  scripts\mem0_local_write_read_canary.py `
  scripts\build_mem0_write_gate_packet.py `
  scripts\build_dj_collaboration_graph.py `
  scripts\recommend_graph_similarity.py `
  scripts\build_trending_index.py `
  scripts\recommend_hybrid.py `
  scripts\graph_rag_nl_to_cypher.py `
  scripts\graph_rag_retrieve.py `
  scripts\graph_rag_hybrid_context.py `
  scripts\graph_rag_answer.py `
  scripts\validate_weekly_schema_compat.py `
  scripts\run_e2e_integration_test.py `
  scripts\build_weekly_event_published_canary.py `
  scripts\trace_weekly_time_iso_gap.py `
  scripts\decide_weekly_publish_path.py `
  scripts\summarize_prd_longrun_status.py `
  scripts\build_canonical_entities.py `
  scripts\validate_graph_promotion_readiness.py `
  scripts\validate_consumer_deploy_readiness.py `
  scripts\promote_graph_to_production.py `
  scripts\consumer_query_smoke.py `
  scripts\extract_ocr_entities.py `
  scripts\merge_ocr_entities_to_neo4j.py `
  scripts\audit_ocr_reflow_readiness.py `
  scripts\extract_ocr_entities_from_sidecar.py `
  scripts\audit_poster_ocr_text_gate.py `
  scripts\review_social_identity_cross_evidence.py `
  scripts\synthesize_ocr_asset_blockers.py `
  scripts\build_final_full_pipeline_readiness.py `
  scripts\build_full_pipeline_launch_packet.py `
  scripts\build_full_pipeline_release_candidate_manifest.py `
  scripts\build_full_pipeline_production_operation_packet.py `
  scripts\build_language_field_vector_jobs.py `
  scripts\build_vector_role_artifacts.py `
  scripts\run_full_vectorize_endpoint.py `
  scripts\qdrant_full_staging_writer.py `
  scripts\stage7_runtime_guard.py `
  scripts\embed_vector_role_artifact.py `
  scripts\qdrant_vector_role_staging_writer.py `
  scripts\run_vector_router_smoke.py `
  scripts\run_vector_semantic_router_eval.py `
  scripts\run_vector_role_full_wave.py `
  scripts\run_vector_collection_router_smoke.py `
  scripts\qdrant_role_alias_gate.py `
  scripts\apply_qdrant_role_alias_gate.py `
  scripts\run_qdrant_role_alias_router_smoke.py `
  scripts\qdrant_alias_promote.py `
  scripts\bench_bge_m3.py `
  scripts\build_graph_rag_recommendation_current_smoke.py `
  scripts\verify_cloudrun_stage7_packaging.py `
  scripts\build_cloudrun_deploy_execution_report.py `
  scripts\smoke_cloudrun_stage7_production.py `
  scripts\smoke_cloudrun_weekly_production.py `
  scripts\audit_stage7_unfinished_longrun_plans.py `
  scripts\build_recovered_artifact_manifest.py `
  scripts\audit_ocr_md_deepseek_contract.py `
  scripts\build_production_gate_cancellation_packet.py `
  scripts\build_stage7_integrated_design_execution_plan.py `
  scripts\build_miniprogram_upload_execution_report.py `
  scripts\build_miniprogram_review_submission_boundary.py `
  scripts\build_production_sqlite_surface_decision.py `
  scripts\build_superlongrun_production_state_packet.py `
  scripts\reconcile_93k_live_status.py `
  scripts\build_stage7_data_completeness_gap_ledger.py `
  scripts\build_v6_p1_existing_ocr_locator.py `
  scripts\build_v6_p1_ocr_markdown_merge_inputs.py `
  scripts\run_v6_p1_local_ocr_repair.py `
  scripts\merge_stable_article_jsonl.py `
  scripts\build_v6_47k_merge_readiness_packet.py `
  scripts\build_graph_external_evidence_seed_queue.py `
  scripts\run_graph_external_evidence_http_fast.py `
  scripts\build_graph_maigret_candidates_from_seed_queue.py `
  scripts\build_graph_external_identity_review_queue.py `
  scripts\adjudicate_graph_external_identity_queue.py `
  scripts\run_external_identity_source_followup.py `
  scripts\build_external_identity_source_followup_review_gate.py `
  scripts\build_graph_candidate_pack_readiness.py `
  scripts\recover_external_identity_source_context.py `
  scripts\build_external_identity_source_context_decision_packet.py `
  scripts\build_atlas_full_source_lineage.py `
  scripts\build_atlas_gap_backfill_execution_packet.py `
  scripts\build_wechat_graph_pipeline_code_inventory.py `
  scripts\recover_maigret_web_container_reports.py `
  scripts\audit_stage7_graph_artifact_rounds.py `
  scripts\audit_stage7_doc_truth_sync.py `
  scripts\audit_wechat_graph_pipeline_doc_truth_sync.py `
  ..\..\services\weekly_activity_cloudrun\scripts\bake_stage7_atlas.py `
  ..\..\services\weekly_activity_cloudrun\scripts\bake_and_deploy.py `
  ..\..\services\weekly_activity_cloudrun\scripts\direct_cloudbase_deploy.py

Write-Host "`n== CloudRun Stage7 atlas API tests =="
Push-Location -LiteralPath "..\..\services\weekly_activity_cloudrun"
try {
  npm test -- --test-name-pattern=Stage7
}
finally {
  Pop-Location
}

Write-Host "`n== Report existence =="
$required = @(
  "STAGE7_DEEPSEEK_V4_PRO_HANDOFF_20260515.md",
  "STAGE7_FULL_DOC_CODE_AUDIT_20260515.md",
  "STAGE7_PIPELINE_PARAMETER_RUNBOOK_20260515.md",
  "STAGE7_GRAPH_CURRENT_AUTHORITY_20260518.md",
  "STAGE7_KEY_FINDINGS_AND_FIXES_20260518.md",
  "scripts\run_current_vector_full_wave_sequence_20260518.ps1",
  "..\..\docs\ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md",
  "..\..\docs\ELECTRONIC_MUSIC_GRAPH_PIPELINE_STAGE_MAP_20260518.md",
  "reports\stage7_pipeline_analysis_20260515.html",
  "reports\p1_maigret_source_validation_20260515\maigret_source_validation_summary.json",
  "reports\p1_cdcr_fallback_canary_20260515\cdcr_fallback_canary_summary.json",
  "reports\p1_public_social_link_validation_20260515\public_social_link_validation_summary.json",
  "reports\p1_social_graph_acceptance_pack_20260515\graph_acceptance_pack_summary.json",
  "reports\p1_social_candidate_review_20260515\social_candidate_review_summary.json",
  "reports\neo4j_p1_social_staging_20260515\neo4j_p1_social_staging_report.json",
  "reports\neo4j_p1_social_staging_20260515\canary_verification.json",
  "reports\consumer_publish_gate_review_20260515\consumer_publish_gate_review.json",
  "reports\ocr_file_index_20260515\ocr_file_index_summary.json",
  "reports\ocr_file_index_latest.json",
  "reports\ocr_canary_queue_20260515\ocr_canary_queue_summary.json",
  "reports\dajiala_roi_budget_gate_packet_20260518\dajiala_roi_budget_gate_packet.json",
  "reports\dajiala_roi_budget_gate_packet_20260518\dajiala_roi_budget_gate_packet.md",
  "reports\dajiala_roi_budget_gate_packet_wave07_20260518\dajiala_roi_budget_gate_packet.json",
  "reports\dajiala_paid_wave07_execution_packet_20260518\dajiala_paid_wave_execution_packet.json",
  "reports\dajiala_paid_wave07_execution_packet_20260518\dajiala_paid_wave07.jsonl",
  "reports\dajiala_paid_wave07_archive_20260517\dajiala-repair-status.json",
  "reports\dajiala_paid_wave07_archive_20260517\dajiala_success_selection_summary.json",
  "reports\dajiala_paid_wave07_archive_20260517\asset-retention-status.json",
  "reports\dajiala_paid_wave07_archive_20260517\dajiala_success_image_split_summary.json",
  "reports\dajiala_paid_wave07_process_20260518\batch-status.json",
  "reports\dajiala_paid_wave07_process_20260518\poster-ocr-status.json",
  "reports\dajiala_paid_wave07_ocr_manifest_20260518\summary.json",
  "reports\dajiala_paid_wave07_ocr_index_20260518\ocr_file_index_summary.json",
  "reports\dajiala_paid_wave01_07_verified_combined_ocr_index_20260518\ocr_file_index_summary.json",
  "reports\dajiala_paid_wave01_07_verified_poster_text_vector_jobs_20260518\poster_text_vector_jobs_summary.json",
  "reports\qdrant_poster_staging_wave01_07_20260518\qdrant_poster_staging_report.json",
  "reports\poster_vector_write_gate_packet_wave01_07_20260518\poster_vector_write_gate_packet.json",
  "reports\dajiala_paid_wave01_07_verified_ocr_entity_extraction_20260518\ocr_entity_extraction_summary.json",
  "reports\dajiala_paid_wave01_07_verified_ocr_entity_merge_20260518\ocr_entity_merge_report.json",
  "reports\ocr_entity_merge_write_gate_packet_wave01_07_20260518\ocr_entity_merge_write_gate_packet.json",
  "STAGE7_ALL_PLANS_LANDED_20260518.md",
  "reports\all_plans_landed_20260518\all_plans_landed.json",
  "reports\all_plans_landed_20260518\all_plans_landed.md",
  "C:\code\local-deep-research-wechat\source_pack\code__githubstar__wechathtmldownload__reports__TASK_COMPLETION_DEEP_RESEARCH_20260518.md",
  "C:\code\local-deep-research-wechat\source_pack\code__githubstar__wechathtmldownload__reports__WECHAT_TOTAL_DEEP_AUDIT_wechat_total_deep_audit_20260518.md",
  "C:\code\local-deep-research-wechat\source_pack\code__githubstar__wechathtmldownload__reports__MAIN_THREAD_BRIEFING_DEEP_RESEARCH_LAYER_20260518.md",
  "C:\code\local-deep-research-wechat\source_pack\agent-comm__docs__WECHAT_FULL_RESEARCH_TOOL_AI_MANUAL.md",
  "C:\code\local-deep-research-wechat\data\library_upload_ready\manifest.json",
  "C:\code\local-deep-research-wechat\make-library-upload-bundle.ps1",
  "reports\stage7_integrated_design_execution_plan_20260518\stage7_integrated_design_execution_plan.json",
  "reports\stage7_integrated_design_execution_plan_20260518\stage7_integrated_design_execution_plan.md",
  "reports\miniprogram_upload_20260518\upload_2026.05.18.1.log",
  "reports\miniprogram_upload_20260518\miniprogram_upload_execution_report.json",
  "reports\miniprogram_upload_20260518\miniprogram_upload_execution_report.md",
  "reports\miniprogram_review_submission_boundary_20260518\miniprogram_review_submission_boundary.json",
  "reports\miniprogram_review_submission_boundary_20260518\miniprogram_review_submission_boundary.md",
  "reports\production_sqlite_surface_decision_20260518\production_sqlite_surface_decision.json",
  "reports\production_sqlite_surface_decision_20260518\production_sqlite_surface_decision.md",
  "reports\consumer_release_pack_full_unknown_time_20260514\release_pointer.staging.json",
  "reports\consumer_release_pointer_smoke_20260514\consumer_release_pointer_smoke.json",
  "reports\consumer_unknown_time_compat_20260514\consumer_unknown_time_compat.json",
  "reports\hermes_heartbeat_20260515\heartbeat_latest.json",
  "reports\hermes_metrics_20260515\metrics_snapshot.json",
  "reports\hermes_alerts_20260515\alerts.json",
  "reports\hermes_cost_20260515\cost_summary.json",
  "reports\hermes_dashboard_20260515\hermes_dashboard.html",
  "reports\publish_time_content_extraction_20260515\content_dates_summary.json",
  "reports\publish_time_html_extraction_20260515\html_dates_summary.json",
  "reports\publish_time_url_analysis_20260515\url_dates_summary.json",
  "reports\publish_time_consolidated_20260515\publish_time_consolidated_summary.json",
  "reports\consumer_release_pack_with_time_probe_20260515\manifest.json",
  "reports\p1_cdcr_direct_source_20260515\cdcr_direct_source_summary.json",
  "reports\social_deep_candidates_20260515\social_deep_candidates_summary.json",
  "reports\soundcloud_canary_20260515\soundcloud_profile_canary_summary.json",
  "reports\bandcamp_canary_20260515\bandcamp_profile_canary_summary.json",
  "reports\linktree_canary_20260515\linktree_parse_summary.json",
  "reports\social_deep_edge_pack_20260515\social_deep_edge_pack_summary.json",
  "reports\social_deep_neo4j_20260515\neo4j_p1_social_staging_report.json",
  "reports\storage_migration_20260515\storage_migration_summary.json",
  "reports\storage_migration_20260515\qdrant_collection_candidates.jsonl",
  "reports\storage_migration_20260515\snapshot_manifest.json",
  "reports\storage_migration_20260515\snapshot_report.md",
  "reports\storage_migration_20260515\snapshot_phase2_summary.json",
  "reports\storage_migration_20260515\snapshot_phase2_summary.md",
  "reports\mem0_dimension_gate_20260515\mem0_dimension_gate.json",
  "reports\mem0_dimension_gate_20260515\mem0_dimension_gate.md",
  "reports\mem0_design_20260515\mem0_integration_design.json",
  "reports\mem0_design_20260515\mem0_integration_design.md",
  "reports\mem0_local_write_read_canary_20260518\mem0_local_write_read_canary.json",
  "reports\mem0_write_gate_packet_20260518\mem0_write_gate_packet.json",
  "reports\dj_collab_graph_20260515\dj_collab_graph_summary.json",
  "reports\dj_collab_graph_20260515\dj_collab_edges.jsonl",
  "reports\graph_recommend_canary_20260515\graph_recommend_canary.json",
  "reports\trending_index_20260515\trending_index_summary.json",
  "reports\trending_index_20260515\trending_index.jsonl",
  "reports\hybrid_recommend_canary_20260515\hybrid_recommend_canary.json",
  "reports\hybrid_recommend_canary_20260515\hybrid_recommend_canary.md",
  "queries\graph_rag_test_queries.jsonl",
  "reports\graph_rag_nl2cypher_20260515\graph_rag_nl2cypher_summary.json",
  "reports\graph_rag_nl2cypher_20260515\graph_rag_cypher_plans.jsonl",
  "reports\graph_rag_retrieve_20260515\graph_rag_retrieve_summary.json",
  "reports\graph_rag_retrieve_20260515\graph_rag_contexts.jsonl",
  "reports\graph_rag_hybrid_context_20260515\graph_rag_hybrid_context_summary.json",
  "reports\graph_rag_hybrid_context_20260515\graph_rag_hybrid_contexts.jsonl",
  "reports\graph_rag_answer_20260515\graph_rag_answer_summary.json",
  "reports\graph_rag_answer_20260515\graph_rag_answer_drafts.jsonl",
  "reports\e2e_integration_20260515\schema_compat_report.json",
  "reports\e2e_integration_20260515\schema_compat_report.md",
  "reports\e2e_integration_20260515\e2e_integration_report.json",
  "reports\e2e_integration_20260515\e2e_integration_report.md",
  "reports\weekly_event_published_canary_20260515\weekly_event_published_canary.json",
  "reports\weekly_event_published_canary_20260515\weekly_event_published_canary.md",
  "reports\weekly_event_published_canary_20260515\weekly_event_published_candidates.jsonl",
  "reports\weekly_time_iso_gap_trace_20260515\weekly_time_iso_gap_trace.json",
  "reports\weekly_time_iso_gap_trace_20260515\weekly_time_iso_gap_trace.md",
  "reports\weekly_publish_path_decision_20260515\weekly_publish_path_decision.json",
  "reports\weekly_publish_path_decision_20260515\weekly_publish_path_decision.md",
  "reports\prd_longrun_status_20260515\prd_longrun_status.json",
  "reports\prd_longrun_status_20260515\prd_longrun_status.md",
  "reports\canonical_entities_20260515\canonical_entities_summary.json",
  "reports\canonical_entities_20260515\canonical_entities_summary.md",
  "reports\canonical_entities_20260515\canonical_index.jsonl",
  "reports\canonical_entities_20260515\canonical_review_candidates.jsonl",
  "reports\graph_promotion_readiness_20260515\graph_promotion_readiness.json",
  "reports\graph_promotion_readiness_20260515\graph_promotion_readiness.md",
  "reports\consumer_deploy_readiness_20260515\consumer_deploy_readiness.json",
  "reports\consumer_deploy_readiness_20260515\consumer_deploy_readiness.md",
  "reports\ocr_entity_extraction_20260515\ocr_entity_extraction_summary.json",
  "reports\ocr_entity_extraction_20260515\ocr_entity_extraction_summary.md",
  "reports\ocr_entity_extraction_20260515\ocr_entities.jsonl",
  "reports\ocr_entity_merge_20260515\ocr_entity_merge_report.json",
  "reports\ocr_entity_merge_20260515\ocr_entity_merge_report.md",
  "reports\ocr_entity_merge_20260515\ocr_entity_merge_plan.jsonl",
  "reports\ocr_reflow_readiness_20260515\ocr_reflow_readiness.json",
  "reports\ocr_reflow_readiness_20260515\ocr_reflow_readiness.md",
  "reports\ocr_sidecar_entity_extraction_20260515\ocr_sidecar_entity_extraction_summary.json",
  "reports\ocr_sidecar_entity_extraction_20260515\ocr_sidecar_entity_extraction_summary.md",
  "reports\ocr_sidecar_entity_extraction_20260515\ocr_entities.jsonl",
  "reports\ocr_sidecar_entity_merge_20260515\ocr_entity_merge_report.json",
  "reports\ocr_sidecar_entity_merge_20260515\ocr_entity_merge_report.md",
  "reports\ocr_sidecar_entity_merge_20260515\ocr_entity_merge_plan.jsonl",
  "reports\poster_ocr_text_gate_refresh_20260515\poster_ocr_text_gate_refresh.json",
  "reports\poster_ocr_text_gate_refresh_20260515\poster_ocr_text_gate_refresh.md",
  "reports\poster_ocr_text_gate_refresh_20260515\poster_ocr_text_candidates.jsonl",
  "reports\social_identity_cross_evidence_20260515\identity_cross_evidence_summary.json",
  "reports\social_identity_cross_evidence_20260515\identity_cross_evidence_summary.md",
  "reports\social_identity_cross_evidence_20260515\identity_cross_evidence_review.jsonl",
  "reports\social_identity_cross_evidence_20260515\accepted_social_edges_after_identity_review.jsonl",
  "reports\ocr_asset_blocker_synthesis_20260515\ocr_asset_blocker_synthesis.json",
  "reports\ocr_asset_blocker_synthesis_20260515\ocr_asset_blocker_synthesis.md",
  "reports\final_full_pipeline_readiness_20260515\final_full_pipeline_readiness.json",
  "reports\final_full_pipeline_readiness_20260515\final_full_pipeline_readiness.md",
  "reports\pipeline_status_93k_live_reconcile_20260517\pipeline_status_93k_live_reconcile.json",
  "reports\pipeline_status_93k_live_reconcile_20260517\pipeline_status_93k_live_reconcile.md",
  "reports\consumer_release_pack_full_unknown_time_20260517\manifest.json",
  "reports\consumer_release_pack_full_unknown_time_20260517\release_pointer.staging.json",
  "reports\consumer_release_pointer_smoke_20260517\consumer_release_pointer_smoke.json",
  "reports\consumer_unknown_time_compat_20260517\consumer_unknown_time_compat.json",
  "reports\weekly_schema_compat_full_20260517\schema_compat_report.json",
  "reports\e2e_integration_release_pack_consumer_20260517\e2e_integration_report.json",
  "reports\consumer_publish_gate_review_20260517\consumer_publish_gate_review.json",
  "reports\consumer_deploy_readiness_20260517\consumer_deploy_readiness.json",
  "reports\consumer_production_gate_packet_20260517\consumer_production_gate_packet.json",
  "reports\graph_production_promotion_verify_20260517\promotion_report.json",
  "reports\consumer_query_smoke_production_labels_20260517\consumer_query_smoke.json",
  "reports\dj_collab_graph_20260517\dj_collab_graph_summary.json",
  "reports\graph_recommend_canary_20260517\graph_recommend_canary.json",
  "reports\trending_index_20260517\trending_index_summary.json",
  "reports\hybrid_recommend_canary_20260517\hybrid_recommend_canary.json",
  "reports\graph_rag_nl2cypher_20260517\graph_rag_nl2cypher_summary.json",
  "reports\graph_rag_retrieve_20260517\graph_rag_retrieve_summary.json",
  "reports\graph_rag_hybrid_context_20260517\graph_rag_hybrid_context_summary.json",
  "reports\graph_rag_answer_20260517\graph_rag_answer_summary.json",
  "reports\prd_longrun_status_20260517_verified\prd_longrun_status.json",
  "reports\final_full_pipeline_readiness_20260517_verified\final_full_pipeline_readiness.json",
  "reports\e2e_integration_full_20260517\e2e_integration_report.json",
  "reports\full_pipeline_launch_packet_20260517\full_pipeline_launch_packet.json",
  "reports\full_pipeline_launch_packet_20260517\full_pipeline_launch_packet.md",
  "reports\full_pipeline_release_candidate_20260517\release_candidate_manifest.json",
  "reports\full_pipeline_release_candidate_20260517\release_candidate_manifest.md",
  "reports\full_pipeline_production_operation_packet_20260517\full_pipeline_production_operation_packet.json",
  "reports\full_pipeline_production_operation_packet_20260517\full_pipeline_production_operation_packet.md",
  "reports\full_pipeline_production_operation_packet_20260517\weekly_bake_and_deploy_dry_run.log",
  "reports\embedding_model_matrix_eval_20260517\PIPELINE_INTEGRATION_REPLACEMENT_PLAN_2026-05-17.md",
  "reports\language_field_vector_jobs_canary_20260517\schema_report.json",
  "reports\language_field_vector_jobs_canary_20260517\sample_review.md",
  "reports\language_field_vector_jobs_full_20260517\schema_report.json",
  "reports\language_field_vector_jobs_full_20260517\sample_review.md",
  "reports\language_field_vector_jobs_full_20260517\vector_jobs.jsonl",
  "reports\vector_role_artifacts_canary_20260518_fast\role_artifacts_summary.json",
  "reports\vector_role_artifacts_20260518\role_artifacts_summary.json",
  "reports\vector_role_artifacts_20260518\snowflake_canary\card_texts.jsonl",
  "reports\vector_role_artifacts_20260518\english_sidecar\card_texts.jsonl",
  "reports\consumer_publish_gate_review_20260518\consumer_publish_gate_review.json",
  "reports\production_gate_cancellation_20260518\production_gate_cancellation_packet.json",
  "reports\production_gate_cancellation_20260518\production_gate_cancellation_packet.md",
  "reports\vector_role_embedding_canary_20260518\snowflake_canary\embedding_report.json",
  "reports\vector_role_embedding_canary_20260518\snowflake_canary\embeddings.jsonl",
  "reports\vector_role_embedding_canary_20260518\english_sidecar\embedding_report.json",
  "reports\vector_role_embedding_canary_20260518\english_sidecar\embeddings.jsonl",
  "reports\qdrant_vector_role_staging_snowflake_canary_20260518\qdrant_vector_role_staging_report.json",
  "reports\qdrant_vector_role_staging_english_sidecar_canary_20260518\qdrant_vector_role_staging_report.json",
  "reports\vector_router_smoke_20260518\vector_router_smoke.json",
  "reports\vector_router_smoke_20260518\vector_router_smoke.md",
  "reports\vector_semantic_router_eval_20260518\vector_semantic_router_eval.json",
  "reports\vector_semantic_router_eval_20260518\vector_semantic_router_eval.md",
  "reports\vector_role_full_wave_canary_20260518\snowflake_canary\qdrant_vector_role_full_wave_report.json",
  "reports\vector_role_full_wave_canary_20260518\english_sidecar\qdrant_vector_role_full_wave_report.json",
  "reports\vector_role_full_wave_20260518\snowflake_canary\qdrant_vector_role_full_wave_report.json",
  "reports\vector_role_full_wave_20260518\english_sidecar\qdrant_vector_role_full_wave_report.json",
  "reports\ocr_md_deepseek_contract_audit_20260518\ocr_md_deepseek_contract_audit.json",
  "reports\ocr_md_deepseek_contract_audit_20260518\ocr_md_deepseek_contract_audit.md",
  "reports\ocr_md_deepseek_contract_audit_20260518\review_queue.jsonl",
  "reports\vector_collection_router_smoke_20260518\vector_collection_router_smoke.json",
  "reports\vector_collection_router_smoke_20260518\vector_collection_router_smoke.md",
  "reports\graph_rag_recommendation_current_smoke_20260518\graph_rag_recommendation_current_smoke.json",
  "reports\graph_rag_recommendation_current_smoke_20260518\graph_rag_recommendation_current_smoke.md",
  "reports\consumer_deploy_readiness_20260518\consumer_deploy_readiness.json",
  "reports\consumer_production_gate_packet_20260518\consumer_production_gate_packet.json",
  "reports\full_pipeline_launch_packet_20260518\full_pipeline_launch_packet.json",
  "reports\full_pipeline_release_candidate_20260518\release_candidate_manifest.json",
  "reports\cloudrun_stage7_packaging_20260518\cloudrun_stage7_packaging.json",
  "reports\cloudrun_stage7_packaging_20260518\cloudrun_stage7_packaging.md",
  "reports\full_pipeline_production_operation_packet_20260518\full_pipeline_production_operation_packet.json",
  "reports\full_pipeline_production_operation_packet_20260518\full_pipeline_production_operation_packet.md",
  "reports\full_pipeline_production_operation_packet_20260518\weekly_bake_and_deploy_dry_run.log",
  "reports\full_pipeline_production_deploy_20260518\weekly_bake_and_deploy.log",
  "reports\full_pipeline_production_deploy_20260518\cloudrun_version_list_after.txt",
  "reports\full_pipeline_production_deploy_20260518\cloudrun_version_list_after_direct_api.txt",
  "reports\full_pipeline_production_deploy_20260518\cloudrun_direct_api_deploy_report.json",
  "reports\full_pipeline_production_deploy_20260518\cloudrun_deploy_execution_report.json",
  "reports\full_pipeline_production_deploy_20260518\cloudrun_deploy_execution_report.md",
  "reports\cloudrun_stage7_production_smoke_20260518\cloudrun_stage7_production_smoke.json",
  "reports\cloudrun_stage7_production_smoke_20260518\cloudrun_stage7_production_smoke.md",
  "reports\cloudrun_weekly_production_smoke_20260518\cloudrun_weekly_production_smoke.json",
  "reports\cloudrun_weekly_production_smoke_20260518\cloudrun_weekly_production_smoke.md",
  "reports\superlongrun_cloudrun_stage7_smoke_20260518\cloudrun_stage7_production_smoke.json",
  "reports\superlongrun_cloudrun_stage7_smoke_20260518\cloudrun_stage7_production_smoke.md",
  "reports\superlongrun_cloudrun_weekly_smoke_20260518\cloudrun_weekly_production_smoke.json",
  "reports\superlongrun_cloudrun_weekly_smoke_20260518\cloudrun_weekly_production_smoke.md",
  "reports\superlongrun_production_state_20260518\superlongrun_production_state.json",
  "reports\superlongrun_production_state_20260518\superlongrun_production_state.md",
  "reports\crash_dump_guard_20260518\crash_dump_guard_report.json",
  "reports\crash_dump_guard_20260518\crash_dump_guard_report.md",
  "reports\stage7_data_completeness_gap_ledger_20260518\gap_ledger.json",
  "reports\stage7_data_completeness_gap_ledger_20260518\gap_ledger.md",
  "reports\v6_p1_existing_ocr_locator_20260518\v6_p1_existing_ocr_locator_summary.json",
  "reports\v6_p1_existing_ocr_locator_20260518\v6_p1_existing_ocr_locator_summary.md",
  "reports\v6_p1_ocr_markdown_merge_inputs_20260518\merge_summary.json",
  "reports\v6_p1_ocr_markdown_merge_inputs_20260518\merge_summary.md",
  "reports\v6_p1_ocr_markdown_merge_inputs_20260518\flash_manifest.jsonl",
  "reports\v6_p1_ocr_markdown_flash_select_20260518\flash_select_20\flash_summary.json",
  "reports\v6_p1_ocr_markdown_flash_full1082_20260518\flash_run1082\flash_summary.json",
  "reports\v6_p1_ocr_markdown_flash_full1082_20260518\flash_run1082\flash_rows.repaired.jsonl",
  "reports\v6_p1_ocr_markdown_flash_parse_repair_20260518\flash_repair3\flash_summary.json",
  "reports\v6_p1_ocr_markdown_flash_parse_repair_20260518\parse_repair_merge_summary.json",
  "reports\v6_p1_ocr_markdown_flash_full1082_stable_extract_repaired_20260518\stable_materialize_summary.json",
  "reports\neo4j_v6_p1_ocr_markdown_flash_full1082_staging_apply_20260518\neo4j_stage7_staging_report.json",
  "reports\neo4j_v6_p1_ocr_markdown_flash_full1082_typed_edges_apply_20260518\neo4j_stage7_typed_edge_promotion.json",
  "reports\graph_promotion_readiness_v6_p1_ocr_markdown_flash_full1082_20260518\graph_promotion_readiness.json",
  "reports\graph_production_promotion_v6_p1_ocr_markdown_flash_full1082_verify_20260518\promotion_report.json",
  "reports\v6_p1_local_ocr_repair_20260518\full_remaining_20260518_1458\local_ocr_repair_summary.json",
  "reports\v6_p1_local_ocr_repair_20260518\full_remaining_20260518_1458\local_ocr_repair_summary.md",
  "reports\v6_p1_existing_ocr_locator_after_local_ocr_full_strict_20260518\v6_p1_existing_ocr_locator_summary.json",
  "reports\v6_p1_existing_ocr_locator_after_local_ocr_full_strict_20260518\v6_p1_existing_ocr_low_quality_text_review_needed.jsonl",
  "reports\v6_p1_local_ocr_markdown_merge_inputs_incremental_20260518\merge_summary.json",
  "reports\v6_p1_local_ocr_markdown_merge_inputs_incremental_20260518\flash_manifest.jsonl",
  "reports\v6_p1_local_ocr_markdown_flash_incremental_287_20260518\flash_run287\flash_summary.json",
  "reports\v6_p1_local_ocr_markdown_flash_incremental_287_stable_extract_20260518\stable_materialize_summary.json",
  "reports\neo4j_v6_p1_local_ocr_flash_incremental_287_staging_apply_20260518\neo4j_stage7_staging_report.json",
  "reports\neo4j_v6_p1_local_ocr_flash_incremental_287_typed_edges_apply_20260518\neo4j_stage7_typed_edge_promotion.json",
  "reports\graph_promotion_readiness_v6_p1_local_ocr_flash_incremental_287_20260518\graph_promotion_readiness.json",
  "reports\graph_production_promotion_v6_p1_local_ocr_flash_incremental_287_verify_20260518\promotion_report.json",
  "reports\v6_p1_local_ocr_repair_20260518\second_pass_69_20260518_1610\local_ocr_repair_summary.json",
  "reports\v6_p1_existing_ocr_locator_after_second_pass_20260518\v6_p1_existing_ocr_locator_summary.json",
  "reports\v6_p1_existing_ocr_locator_after_second_pass_20260518\v6_p1_existing_ocr_low_quality_text_review_needed.jsonl",
  "reports\v6_p1_local_ocr_second_pass_merge_inputs_incremental_28_20260518\merge_summary.json",
  "reports\v6_p1_local_ocr_second_pass_merge_inputs_incremental_28_20260518\flash_manifest.jsonl",
  "reports\v6_p1_local_ocr_second_pass_flash_incremental_28_20260518\flash_run28\flash_summary.json",
  "reports\v6_p1_local_ocr_second_pass_flash_incremental_28_stable_extract_20260518\stable_materialize_summary.json",
  "reports\neo4j_v6_p1_local_ocr_second_pass_flash_incremental_28_staging_apply_20260518\neo4j_stage7_staging_report.json",
  "reports\neo4j_v6_p1_local_ocr_second_pass_flash_incremental_28_typed_edges_apply_20260518\neo4j_stage7_typed_edge_promotion.json",
  "reports\graph_promotion_readiness_v6_p1_local_ocr_second_pass_flash_incremental_28_20260518\graph_promotion_readiness.json",
  "reports\graph_production_promotion_v6_p1_local_ocr_second_pass_flash_incremental_28_verify_20260518\promotion_report.json",
  "reports\stable_merge_47k_plus_v6_p1_repair_1082_20260518\stable_merge_summary.json",
  "reports\stable_merge_47k_plus_v6_p1_repair_1369_20260518\stable_merge_summary.json",
  "reports\stable_merge_47k_plus_v6_p1_repair_1397_20260518\stable_merge_summary.json",
  "reports\v6_47k_merge_readiness_packet_20260518\v6_47k_merge_readiness_packet.json",
  "reports\v6_47k_merge_readiness_packet_20260518\v6_47k_merge_readiness_packet.md",
  "reports\neo4j_47k_plus_v6_p1_repair_1397_staging_apply_20260518\neo4j_stage7_staging_report.json",
  "reports\neo4j_47k_plus_v6_p1_repair_1397_typed_edges_apply_20260518\neo4j_stage7_typed_edge_promotion.json",
  "reports\graph_promotion_readiness_47k_plus_v6_p1_repair_1397_20260518\graph_promotion_readiness.json",
  "reports\graph_production_promotion_47k_plus_v6_p1_repair_1397_verify_20260518\promotion_report.json",
  "reports\stage7_graph_artifact_rounds_reconciliation_20260518\graph_artifact_rounds_reconciliation.json",
  "reports\dajiala_paid_wave01_21_verified_combined_ocr_index_20260518\ocr_file_index_summary.json",
  "reports\ocr_md_deepseek_contract_audit_wave09_21_20260518\ocr_md_deepseek_contract_audit.json",
  "reports\ocr_markitdown_flash_reprocess_plan_wave01_21_20260518\ocr_markitdown_flash_reprocess_plan.json",
  "reports\ocr_markitdown_flash_reprocess_plan_wave09_21_delta_20260518\delta_manifest_summary.json",
  "reports\ocr_markitdown_flash_reprocess_flash_wave09_21_delta375_20260518\flash_run375_verified_ocr_delta\flash_summary.json",
  "reports\ocr_markdown_flash_wave09_21_delta375_stable_extract_20260518\stable_materialize_summary.json",
  "reports\neo4j_ocr_markdown_flash_wave09_21_delta375_staging_apply_20260518\neo4j_stage7_staging_report.json",
  "reports\neo4j_ocr_markdown_flash_wave09_21_delta375_typed_edges_apply_20260518\neo4j_stage7_typed_edge_promotion.json",
  "reports\graph_promotion_readiness_ocr_markdown_flash_wave09_21_delta375_20260518\graph_promotion_readiness.json",
  "reports\graph_production_promotion_ocr_markdown_flash_wave09_21_delta375_verify_20260518\promotion_report.json",
  "reports\stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518\stable_merge_summary.json",
  "reports\neo4j_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_staging_apply_20260518\neo4j_stage7_staging_report.json",
  "reports\neo4j_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_typed_edges_apply_20260518\neo4j_stage7_typed_edge_promotion.json",
  "reports\graph_promotion_readiness_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518\graph_promotion_readiness.json",
  "reports\graph_production_promotion_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_verify_20260518\promotion_report.json",
  "reports\graph_external_evidence_seed_queue_47k_plus_paid_20260518\seed_queue_summary.json",
  "reports\graph_external_evidence_seed_queue_47k_plus_paid_20260518\external_evidence_seed_queue.jsonl",
  "reports\graph_external_evidence_http_fast_47k_plus_paid_20260518\http_fast_summary.json",
  "reports\graph_external_evidence_http_fast_47k_plus_paid_20260518\http_fast_results.jsonl",
  "reports\graph_maigret_candidates_47k_plus_paid_20260518\maigret_candidate_summary.json",
  "reports\graph_maigret_candidates_47k_plus_paid_20260518\maigret_candidates.jsonl",
  "reports\graph_maigret_canary_47k_plus_paid_20260518\maigret_canary_summary.json",
  "reports\graph_maigret_canary_47k_plus_paid_20260518\maigret_canary_recovered_summary.json",
  "reports\graph_maigret_canary_47k_plus_paid_20260518\maigret_normalized_candidate_evidence.jsonl",
  "reports\graph_external_identity_review_queue_47k_plus_paid_20260518\external_identity_review_queue_summary.json",
  "reports\graph_external_identity_review_queue_47k_plus_paid_20260518\external_identity_review_queue.jsonl",
  "reports\graph_external_identity_review_queue_47k_plus_paid_20260518\reachable_url_identity_review_queue.jsonl",
  "reports\graph_external_identity_review_queue_47k_plus_paid_20260518\maigret_identity_review_queue.jsonl",
  "reports\external_identity_adjudication_47k_delta375_20260519\external_identity_adjudication_summary.json",
  "reports\external_identity_adjudication_47k_delta375_20260519\external_identity_adjudication_summary.md",
  "reports\external_identity_adjudication_47k_delta375_20260519\external_identity_adjudication_review.jsonl",
  "reports\external_identity_adjudication_47k_delta375_20260519\external_identity_source_followup_queue.jsonl",
  "reports\external_identity_adjudication_47k_delta375_20260519\accepted_external_identity_edges_for_graph.jsonl",
  "reports\external_identity_source_followup_47k_delta375_20260519\source_followup_summary.json",
  "reports\external_identity_source_followup_47k_delta375_20260519\source_followup_summary.md",
  "reports\external_identity_source_followup_47k_delta375_20260519\source_followup_review.jsonl",
  "reports\external_identity_source_followup_47k_delta375_20260519\accepted_external_identity_edges_for_graph.jsonl",
  "reports\external_identity_source_followup_candidate_only_47k_delta375_20260519\source_followup_summary.json",
  "reports\external_identity_source_followup_candidate_only_47k_delta375_20260519\source_followup_summary.md",
  "reports\external_identity_source_followup_candidate_only_47k_delta375_20260519\source_followup_review.jsonl",
  "reports\external_identity_source_followup_candidate_only_47k_delta375_20260519\accepted_external_identity_edges_for_graph.jsonl",
  "reports\external_identity_source_followup_review_gate_47k_delta375_20260519\source_followup_review_gate_summary.json",
  "reports\external_identity_source_followup_review_gate_47k_delta375_20260519\source_followup_review_gate_summary.md",
  "reports\external_identity_source_followup_review_gate_47k_delta375_20260519\source_followup_review_gate.jsonl",
  "reports\external_identity_source_followup_review_gate_47k_delta375_20260519\rejected_or_needs_more_source.jsonl",
  "reports\external_identity_source_followup_review_gate_47k_delta375_20260519\accepted_external_identity_edges_for_graph.jsonl",
  "reports\graph_candidate_pack_readiness_47k_delta375_20260519\graph_candidate_pack_readiness.json",
  "reports\graph_candidate_pack_readiness_47k_delta375_20260519\graph_candidate_pack_readiness.md",
  "reports\graph_candidate_pack_readiness_47k_delta375_20260519\external_identity_edges_for_graphcandidatepack.jsonl",
  "reports\graph_candidate_pack_readiness_47k_delta375_20260519\external_identity_needs_more_source_queue.jsonl",
  "reports\external_identity_source_context_recovery_47k_delta375_20260519\source_context_recovery_summary.json",
  "reports\external_identity_source_context_recovery_47k_delta375_20260519\source_context_recovery_summary.md",
  "reports\external_identity_source_context_recovery_47k_delta375_20260519\source_context_recovery.jsonl",
  "reports\external_identity_source_context_recovery_47k_delta375_20260519\source_context_recovered_candidates.jsonl",
  "reports\external_identity_source_context_recovery_47k_delta375_20260519\accepted_external_identity_edges_for_graph.jsonl",
  "reports\external_identity_source_context_decision_47k_delta375_20260519\source_context_decision_summary.json",
  "reports\external_identity_source_context_decision_47k_delta375_20260519\source_context_decision_summary.md",
  "reports\external_identity_source_context_decision_47k_delta375_20260519\source_context_decision.jsonl",
  "reports\external_identity_source_context_decision_47k_delta375_20260519\future_direct_proof_pass_queue.jsonl",
  "reports\external_identity_source_context_decision_47k_delta375_20260519\review_only_context_queue.jsonl",
  "reports\external_identity_source_context_decision_47k_delta375_20260519\rejected_source_context_only_for_graph.jsonl",
  "reports\external_identity_source_context_decision_47k_delta375_20260519\accepted_external_identity_edges_for_graph.jsonl",
  "reports\external_identity_future_direct_proof_followup_47k_delta375_20260519\source_followup_summary.json",
  "reports\external_identity_future_direct_proof_followup_47k_delta375_20260519\source_followup_summary.md",
  "reports\external_identity_future_direct_proof_followup_47k_delta375_20260519\source_followup_review.jsonl",
  "reports\external_identity_future_direct_proof_followup_47k_delta375_20260519\accepted_external_identity_edges_for_graph.jsonl",
  "reports\external_identity_future_direct_proof_review_gate_47k_delta375_20260519\source_followup_review_gate_summary.json",
  "reports\external_identity_future_direct_proof_review_gate_47k_delta375_20260519\source_followup_review_gate_summary.md",
  "reports\external_identity_future_direct_proof_review_gate_47k_delta375_20260519\source_followup_review_gate.jsonl",
  "reports\external_identity_future_direct_proof_review_gate_47k_delta375_20260519\rejected_or_needs_more_source.jsonl",
  "reports\external_identity_future_direct_proof_review_gate_47k_delta375_20260519\accepted_external_identity_edges_for_graph.jsonl",
  "reports\graph_candidate_pack_final_lock_47k_delta375_20260519\graph_candidate_pack_readiness.json",
  "reports\graph_candidate_pack_final_lock_47k_delta375_20260519\graph_candidate_pack_readiness.md",
  "reports\graph_candidate_pack_final_lock_47k_delta375_20260519\external_identity_edges_for_graphcandidatepack.jsonl",
  "reports\graph_candidate_pack_final_lock_47k_delta375_20260519\external_identity_needs_more_source_queue.jsonl",
  "reports\graph_rag_recommendation_current_smoke_47k_delta375_final_lock_20260519\graph_rag_recommendation_current_smoke.json",
  "reports\graph_rag_recommendation_current_smoke_47k_delta375_final_lock_20260519\graph_rag_recommendation_current_smoke.md",
  "reports\atlas_full_source_lineage_47k_93k_gap_20260519\atlas_full_source_lineage.json",
  "reports\atlas_full_source_lineage_47k_93k_gap_20260519\atlas_full_source_lineage.md",
  "reports\atlas_full_source_lineage_47k_93k_gap_20260519\production_source_decision_table.jsonl",
  "reports\atlas_full_source_lineage_47k_93k_gap_20260519\script_path_references.jsonl",
  "reports\atlas_gap_backfill_execution_packet_20260519\gap_backfill_execution_packet.json",
  "reports\atlas_gap_backfill_execution_packet_20260519\gap_backfill_execution_packet.md",
  "reports\atlas_gap_backfill_execution_packet_20260519\gap_backfill_actions.jsonl",
  "reports\vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518\_sequence_status\sequence_status.json",
  "reports\vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518\multilingual_baseline\qdrant_vector_role_full_wave_report.json",
  "reports\vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518\ocr_baseline\qdrant_vector_role_full_wave_report.json",
  "reports\vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518\english_sidecar\qdrant_vector_role_full_wave_report.json",
  "reports\vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518\snowflake_canary\qdrant_vector_role_full_wave_report.json",
  "reports\consumer_release_pack_47k_plus_v6_p1_repair_1397_20260518\manifest.json",
  "reports\language_field_vector_jobs_47k_plus_v6_p1_repair_1397_20260518\schema_report.json",
  "reports\vector_role_artifacts_47k_plus_v6_p1_repair_1397_20260518\role_artifacts_summary.json",
  "reports\vector_full_qwen3_4b_1024_47k_plus_v6_p1_repair_1397_20260518\metadata.json",
  "reports\qdrant_full_qwen3_4b_1024_47k_plus_v6_p1_repair_1397_20260518\qdrant_full_staging_report.json",
  "reports\vector_collection_router_smoke_47k_plus_v6_p1_repair_1397_20260518\vector_collection_router_smoke.json",
  "reports\vector_collection_router_smoke_47k_delta375_roles_20260519\vector_collection_router_smoke.json",
  "reports\vector_collection_router_smoke_47k_delta375_roles_20260519\vector_collection_router_smoke.md",
  "reports\qdrant_role_alias_gate_47k_delta375_20260519\qdrant_role_alias_gate.json",
  "reports\qdrant_role_alias_gate_47k_delta375_20260519\qdrant_role_alias_gate.md",
  "reports\qdrant_role_alias_apply_47k_delta375_20260519\qdrant_role_alias_apply_report.json",
  "reports\qdrant_role_alias_apply_47k_delta375_20260519\qdrant_role_alias_apply_report.md",
  "reports\qdrant_role_alias_apply_47k_delta375_20260519\rollback_actions.json",
  "reports\qdrant_role_alias_apply_47k_delta375_20260519\post_apply_aliases.json",
  "reports\qdrant_role_alias_router_smoke_47k_delta375_20260519\qdrant_role_alias_router_smoke.json",
  "reports\qdrant_role_alias_router_smoke_47k_delta375_20260519\qdrant_role_alias_router_smoke.md",
  "reports\vector_collection_router_smoke_47k_delta375_roles_post_alias_apply_20260519\vector_collection_router_smoke.json",
  "reports\vector_collection_router_smoke_47k_delta375_roles_post_alias_apply_20260519\vector_collection_router_smoke.md",
  "reports\qdrant_role_alias_gate_post_apply_47k_delta375_20260519\qdrant_role_alias_gate.json",
  "reports\qdrant_role_alias_gate_post_apply_47k_delta375_20260519\qdrant_role_alias_gate.md",
  "reports\qdrant_alias_promote_qwen3_47k_plus_v6_p1_repair_1397_20260518\qdrant_alias_promote_report.json",
  "reports\consumer_query_smoke_47k_plus_v6_p1_repair_1397_20260518\consumer_query_smoke.json",
  "config\consumer_publish_gate.local.json",
  "reports\consumer_release_pack_47k_plus_v6_p1_repair_1397_20260518\release_pointer.staging.json",
  "reports\consumer_release_pointer_smoke_47k_plus_v6_p1_repair_1397_20260518\consumer_release_pointer_smoke.json",
  "reports\consumer_unknown_time_compat_47k_plus_v6_p1_repair_1397_20260518\consumer_unknown_time_compat.json",
  "reports\e2e_integration_47k_plus_v6_p1_repair_1397_20260518\e2e_integration_report.json",
  "reports\consumer_publish_gate_review_47k_plus_v6_p1_repair_1397_20260518\consumer_publish_gate_review.json",
  "reports\consumer_deploy_readiness_47k_plus_v6_p1_repair_1397_20260518\consumer_deploy_readiness.json",
  "reports\consumer_production_gate_packet_47k_plus_v6_p1_repair_1397_20260518\consumer_production_gate_packet.json",
  "reports\vector_collection_router_smoke_current_alias_47k_plus_v6_p1_repair_1397_20260518\vector_collection_router_smoke.json",
  "reports\dj_collab_graph_47k_plus_v6_p1_repair_1397_20260518\dj_collab_graph_summary.json",
  "reports\trending_index_47k_plus_v6_p1_repair_1397_20260518\trending_index_summary.json",
  "reports\graph_recommend_canary_47k_plus_v6_p1_repair_1397_20260518\graph_recommend_canary.json",
  "reports\hybrid_recommend_canary_47k_plus_v6_p1_repair_1397_20260518\hybrid_recommend_canary.json",
  "reports\graph_rag_nl2cypher_47k_plus_v6_p1_repair_1397_20260518\graph_rag_nl2cypher_summary.json",
  "reports\graph_rag_retrieve_47k_plus_v6_p1_repair_1397_20260518\graph_rag_retrieve_summary.json",
  "reports\graph_rag_hybrid_context_47k_plus_v6_p1_repair_1397_20260518\graph_rag_hybrid_context_summary.json",
  "reports\graph_rag_answer_47k_plus_v6_p1_repair_1397_20260518\graph_rag_answer_summary.json",
  "reports\graph_rag_recommendation_current_smoke_47k_plus_v6_p1_repair_1397_20260518\graph_rag_recommendation_current_smoke.json",
  "reports\cloudrun_stage7_packaging_47k_plus_v6_p1_repair_1397_20260518\cloudrun_stage7_packaging.json",
  "reports\prd_longrun_status_47k_plus_v6_p1_repair_1397_20260518\prd_longrun_status.json",
  "reports\final_full_pipeline_readiness_47k_plus_v6_p1_repair_1397_20260518\final_full_pipeline_readiness.json",
  "reports\full_pipeline_launch_packet_47k_plus_v6_p1_repair_1397_20260518\full_pipeline_launch_packet.json",
  "reports\full_pipeline_release_candidate_47k_plus_v6_p1_repair_1397_20260518\release_candidate_manifest.json",
  "reports\full_pipeline_production_operation_packet_47k_plus_v6_p1_repair_1397_20260518\full_pipeline_production_operation_packet.json",
  "reports\cloudrun_stage7_local_smoke_47k_plus_v6_p1_repair_1397_20260518\cloudrun_stage7_production_smoke.json",
  "reports\cloudrun_weekly_local_smoke_47k_plus_v6_p1_repair_1397_20260518\cloudrun_weekly_production_smoke.json",
  "reports\full_pipeline_production_deploy_47k_plus_v6_p1_repair_1397_20260518\weekly_bake_and_deploy_dry_run.log",
  "reports\full_pipeline_production_deploy_47k_plus_v6_p1_repair_1397_20260518\weekly_bake_and_deploy.log",
  "reports\full_pipeline_production_deploy_47k_plus_v6_p1_repair_1397_20260518\cloudrun_version_list_after.txt",
  "reports\full_pipeline_production_deploy_47k_plus_v6_p1_repair_1397_20260518\cloudrun_version_list_after_direct_api.txt",
  "reports\full_pipeline_production_deploy_47k_plus_v6_p1_repair_1397_20260518\cloudrun_direct_api_deploy_report.json",
  "reports\full_pipeline_production_deploy_47k_plus_v6_p1_repair_1397_20260518\cloudrun_deploy_execution_report.json",
  "reports\full_pipeline_production_deploy_47k_plus_v6_p1_repair_1397_20260518\cloudrun_deploy_execution_report.md",
  "reports\cloudrun_stage7_production_smoke_47k_plus_v6_p1_repair_1397_20260518\cloudrun_stage7_production_smoke.json",
  "reports\cloudrun_weekly_production_smoke_47k_plus_v6_p1_repair_1397_20260518\cloudrun_weekly_production_smoke.json",
  "reports\superlongrun_production_state_47k_plus_v6_p1_repair_1397_20260518\superlongrun_production_state.json",
  "reports\unfinished_longrun_audit_47k_plus_v6_p1_repair_1397_20260518\unfinished_plan_audit.json",
  "reports\unfinished_longrun_audit_47k_plus_v6_p1_repair_1397_20260518\unfinished_plan_audit.md",
  "reports\dajiala_roi_budget_gate_packet_superlongrun_20260518\dajiala_roi_budget_gate_packet.json",
  "reports\dajiala_roi_budget_gate_packet_superlongrun_20260518\dajiala_roi_budget_gate_packet.md",
  "reports\cloudrun_rollback_to_022_20260518\cloudrun_direct_api_deploy_report.json",
  "reports\cloudrun_rollback_to_022_20260518\cloudrun_deploy_execution_report.json",
  "reports\cloudrun_rollback_to_022_20260518\prepare_release_57_context_with_source_grounded_llm.log",
  "..\..\services\weekly_activity_cloudrun\data\releases\release_lineup_guard_20260517_57\llm\materialize_report.json",
  "reports\unfinished_longrun_audit_20260518\unfinished_plan_audit.json",
  "reports\unfinished_longrun_audit_20260518\unfinished_plan_audit.md",
  "reports\prd_longrun_status_20260518\prd_longrun_status.json",
  "reports\final_full_pipeline_readiness_20260518\final_full_pipeline_readiness.json",
  "..\..\services\weekly_activity_cloudrun\data\stage7_atlas\package_manifest.json",
  "..\..\services\weekly_activity_cloudrun\data\stage7_atlas\release_pointer.staging.json"
)
foreach ($rel in $required) {
  if (-not (Test-Path -LiteralPath $rel)) {
    throw "Missing required artifact: $rel"
  }
  $item = Get-Item -LiteralPath $rel
  Write-Host "OK $rel bytes=$($item.Length)"
}

if (-not $SkipDocker) {
  Write-Host "`n== Docker / local public services =="
  $dockerDir = "C:\Program Files\Docker\Docker\resources\bin"
  if (Test-Path -LiteralPath (Join-Path $dockerDir "docker.exe")) {
    $env:Path = $env:Path + ";" + $dockerDir
  }
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

  $qdrant = Invoke-RestMethod -Uri "http://127.0.0.1:6333/" -TimeoutSec 8
  Write-Host "Qdrant version=$($qdrant.version)"

  $camofox = Invoke-RestMethod -Uri "http://127.0.0.1:9377/health" -TimeoutSec 8
  Write-Host "Camofox ok=$($camofox.ok) activeTabs=$($camofox.activeTabs) activeSessions=$($camofox.activeSessions)"

  $neo4j = Invoke-RestMethod -Uri "http://127.0.0.1:7474/" -TimeoutSec 8
  Write-Host "Neo4j version=$($neo4j.neo4j_version) edition=$($neo4j.neo4j_edition)"
}

Write-Host "`nPASS stage7 safe handoff verify"
