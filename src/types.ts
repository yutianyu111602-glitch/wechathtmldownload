export interface MetaJson {
  source_type: "wechat_article";
  source_url: string;
  title: string;
  account_name: string;
  author_display: string;
  publish_time_text: string;
  publish_time_iso: string;
  page_location_text: string;
  description: string;
  og_image: string;
  content_hash: string;
  html_length: number;
}

export interface ImageAsset {
  src: string;
  data_src: string;
  alt: string;
  title: string;
  width_hint: string;
  ratio_hint: string;
  index: number;
}

export interface AudioCard {
  title: string;
  author: string;
  duration_text: string;
  cover: string;
  voice_encode_fileid: string;
}

export interface VideoCard {
  vid: string;
  title: string;
  cover: string;
}

export interface LinkAsset {
  text: string;
  href: string;
  type: string;
}

export interface AssetsJson {
  images: ImageAsset[];
  audio_cards: AudioCard[];
  video_cards: VideoCard[];
  links: LinkAsset[];
}

export interface BodyBlock {
  type: "paragraph" | "image" | "audio" | "video";
  text?: string;
  src?: string;
  title?: string;
  vid?: string;
}

export interface FooterInfo {
  venue_name_candidate: string;
  venue_address_lines: string[];
  date_texts: string[];
  lineup_lines: string[];
  raw_footer_text: string;
}

export interface RuleExtractJson {
  body_text: string;
  body_blocks: BodyBlock[];
  footer_info: FooterInfo;
  warnings: string[];
}

export interface ProcessArticleResult {
  meta: MetaJson;
  assets: AssetsJson;
  ruleExtract: RuleExtractJson;
  cleanMd: string;
}

export type ProcessPhase =
  | "parse_html"
  | "rule_extract"
  | "markitdown_convert"
  | "markdown_clean"
  | "mirror_llm_md"
  | "write_outputs";

export interface ProcessProgressEvent {
  phase: ProcessPhase;
  step: number;
  totalSteps: number;
  inputPath: string;
  message: string;
}

export type ProcessProgressListener = (
  event: ProcessProgressEvent,
) => void | Promise<void>;

export type BatchItemStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "deferred"
  | "cancelled";

export type BatchItemPhase =
  | ProcessPhase
  | "queued"
  | "succeeded"
  | "failed"
  | "skipped"
  | "deferred"
  | "cancelled";

export interface BatchItemSnapshot {
  inputPath: string;
  relativeInputPath: string;
  outDir: string;
  status: BatchItemStatus;
  phase: BatchItemPhase;
  step: number;
  totalSteps: number;
  message: string;
  errorMessage: string;
  startedAt: string;
  endedAt: string;
}

export interface BatchSnapshot {
  inputRoot: string;
  outRoot: string;
  statusPath: string;
  status: "running" | "completed" | "cancelled";
  startedAt: string;
  endedAt: string;
  totalItems: number;
  queuedCount: number;
  runningCount: number;
  succeededCount: number;
  failedCount: number;
  skippedCount: number;
  cancelledCount: number;
  completedCount: number;
  progressRatio: number;
  currentFile: string;
  currentPhase: ProcessPhase | "";
  itemCount?: number;
  itemLimit?: number;
  itemsTruncated?: boolean;
  items: BatchItemSnapshot[];
}

export type BatchSnapshotListener = (
  snapshot: BatchSnapshot,
) => void | Promise<void>;

export interface RunDualTrackBatchOptions {
  inputRoot: string;
  outRoot: string;
  statusPath?: string;
  resume?: boolean;
  inputMode?: "html" | "archive";
  manifestPath?: string;
  signal?: AbortSignal;
  concurrency?: number;
  onSnapshot?: BatchSnapshotListener;
}

export interface RunLlmExportBatchOptions {
  inputRoot: string;
  outRoot: string;
  mirrorRoot: string;
  statusPath?: string;
  resume?: boolean;
  inputMode?: "html" | "archive";
  manifestPath?: string;
  signal?: AbortSignal;
  concurrency?: number;
  onSnapshot?: BatchSnapshotListener;
}

export interface DualTrackArtifacts {
  markitdownRawMd: string;
  markitdownCleanedMd: string;
  llmInputMd: string;
  markitdownWarnings: string[];
}

export interface ProcessArticleDualTrackResult extends ProcessArticleResult {
  dualTrack: DualTrackArtifacts;
}
