import type {
  AssetsLocalJson,
  ArchiveMetaJson,
  PosterOcrResult,
  QualityReportJson,
  SidecarJson,
} from "../archive/types.js";
import type { AssetsJson, FooterInfo, MetaJson } from "../types.js";
import { buildBackgroundRecall } from "./buildBackgroundRecall.js";
import { cleanLlmContentMarkdown, isLlmShellLine } from "./cleanLlmContent.js";

function buildImageLabel(index: number, title: string, alt: string): string {
  const label = title || alt;
  return label ? `[${index + 1}] ${label}` : `[${index + 1}] 图片`;
}

function uniqueBy<T>(values: T[], key: (value: T) => string): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const value of values) {
    const fingerprint = key(value);
    if (!fingerprint || seen.has(fingerprint)) {
      continue;
    }
    seen.add(fingerprint);
    result.push(value);
  }
  return result;
}

export function buildSidecar(options: {
  inputMode: "html" | "archive";
  meta: MetaJson;
  archiveMeta?: ArchiveMetaJson | null;
  footerInfo: FooterInfo;
  bodyText: string;
  mainMarkdown: string;
  assets: AssetsJson;
  localAssets?: AssetsLocalJson | null;
  posterOcr?: PosterOcrResult;
  warnings?: string[];
}): SidecarJson {
  const mainContent = cleanLlmContentMarkdown(options.mainMarkdown);
  const localImagesByUrl = new Map(
    (options.localAssets?.images ?? []).map((asset) => [asset.remote_url, asset.local_path]),
  );
  const backgroundRecall = buildBackgroundRecall({
    mainContent,
    bodyText: options.bodyText,
    excludedValues: [
      options.meta.title,
      options.meta.account_name,
      options.meta.publish_time_text,
      options.meta.source_url,
      options.archiveMeta?.token || "",
    ],
  });
  const posterOcr: PosterOcrResult = options.posterOcr || {
    imageHeavy: false,
    candidates: [],
    recovered: {},
    warnings: [],
  };

  const images = uniqueBy(
    options.assets.images.map((image) => {
      const remoteUrl = image.data_src || image.src;
      return {
        label: buildImageLabel(image.index, image.title, image.alt),
        remote_url: remoteUrl,
        local_path: localImagesByUrl.get(remoteUrl) || "",
      };
    }),
    (image) => image.remote_url,
  );

  const links = uniqueBy(
    options.assets.links.filter(
      (link) =>
        link.href &&
        !/^javascript:/i.test(link.href.trim()) &&
        !isLlmShellLine(link.text),
    ),
    (link) => `${link.text}|${link.href}`,
  );

  return {
    version: 1,
    input_mode: options.inputMode,
    meta: options.meta,
    footer_info: {
      venue_name_candidate:
        options.footerInfo.venue_name_candidate ||
        posterOcr.recovered.venue_name_candidate ||
        "",
      venue_address_lines: uniqueBy(
        [
          ...options.footerInfo.venue_address_lines,
          ...(posterOcr.recovered.venue_address_lines ?? []),
        ],
        (value) => value,
      ),
      date_texts: uniqueBy(
        [...options.footerInfo.date_texts, ...(posterOcr.recovered.date_texts ?? [])],
        (value) => value,
      ),
      lineup_lines: uniqueBy(
        [...options.footerInfo.lineup_lines, ...(posterOcr.recovered.lineup_lines ?? [])],
        (value) => value,
      ),
      raw_footer_text: options.footerInfo.raw_footer_text,
    },
    archive: options.archiveMeta || null,
    main_content: mainContent,
    background_recall: cleanLlmContentMarkdown(backgroundRecall),
    links,
    images,
    warnings: [...(options.warnings ?? []), ...posterOcr.warnings],
    provenance: {
      primary_source: options.inputMode === "archive" ? "archive/raw.html" : "raw.html",
      fallback_sources:
        options.inputMode === "archive"
          ? ["archive/page.mhtml", "archive/assets_local.json"]
          : [],
    },
    poster_ocr: posterOcr,
  };
}

export function buildQualityReport(sidecar: SidecarJson): QualityReportJson {
  return {
    input_mode: sidecar.input_mode,
    used_local_assets: sidecar.images.some((image) => Boolean(image.local_path)),
    image_count: sidecar.images.length,
    link_count: sidecar.links.length,
    background_recall_chars: sidecar.background_recall.length,
    poster_candidates: sidecar.poster_ocr.candidates.length,
    warnings: sidecar.warnings,
  };
}
