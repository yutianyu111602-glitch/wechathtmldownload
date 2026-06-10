import {
  DEFAULT_ARCHIVE_ROOT,
  DEFAULT_ARTIFACT_ROOT,
  DEFAULT_DISCOVERY_ROOT,
  DEFAULT_IMPORTED_MPTEXT_ROOT,
  DEFAULT_MARKDOWN_MIRROR_ROOT,
  isArchiveWorkspaceRoot,
  resolveArchiveRoot,
  resolveArtifactRoot,
  resolveDiscoveryRoot,
  resolveMptextArchiveRoot,
  resolveReleaseRoot,
} from "./pcuiContract.js";

export const PCUI_ROOT_PROFILE_KEYS = Object.freeze([
  "discoveryRoot",
  "archiveRoot",
  "artifactRoot",
  "markdownMirrorRoot",
  "releaseRoot",
  "mptextRoot",
]);

function readText(readValue) {
  const value = typeof readValue === "function" ? readValue() : readValue;
  return typeof value === "string" ? value.trim() : "";
}

function hasDetectedProcessRoot(appState) {
  return Boolean(appState?.latestProcessState?.sources?.outRoot?.exists && appState?.latestProcessState?.itemCount);
}

export function resolvePcuiRootProfile({
  appState,
  inputPath = "",
  outputPath = "",
  defaults = {},
} = {}) {
  const discoveryFallback = defaults.discoveryRoot || DEFAULT_DISCOVERY_ROOT;
  const archiveFallback = defaults.archiveRoot || DEFAULT_ARCHIVE_ROOT;
  const artifactFallback = defaults.artifactRoot || DEFAULT_ARTIFACT_ROOT;
  const markdownMirrorRoot = defaults.markdownMirrorRoot || DEFAULT_MARKDOWN_MIRROR_ROOT;
  const mptextFallback = defaults.mptextRoot || DEFAULT_IMPORTED_MPTEXT_ROOT;

  const importedDiscoveryRoot = appState?.latestSnapshot?.imported && appState.latestSnapshot.inputRoot
    ? appState.latestSnapshot.inputRoot
    : "";
  const explicitInput = readText(inputPath);
  const discoveryRoot = resolveDiscoveryRoot({
    inputPath: importedDiscoveryRoot && (!explicitInput || explicitInput === discoveryFallback)
      ? importedDiscoveryRoot
      : explicitInput,
    sourceRoot: importedDiscoveryRoot || appState?.latestCollectState?.sources?.rootDir?.path,
    fallback: discoveryFallback,
  });

  const importedArchiveRoot = appState?.latestSnapshot?.imported && isArchiveWorkspaceRoot(appState.latestSnapshot.outRoot)
    ? appState.latestSnapshot.outRoot
    : "";
  const archiveRoot = resolveArchiveRoot({
    inputPath: explicitInput,
    sourceRoot: importedArchiveRoot || appState?.latestArchiveState?.sources?.archiveRoot?.path,
    projectionRoot: appState?.latestAuditProjection?.archiveRoot,
    finalPackArchiveRoot: appState?.latestFinalPackProjection?.archiveRoot,
    fallback: archiveFallback,
  });

  const artifactRoot = resolveArtifactRoot({
    outputPath: readText(outputPath),
    sourceRoot: appState?.latestProcessState?.sources?.outRoot?.path,
    fallback: artifactFallback,
  });
  const releaseRoot = resolveReleaseRoot({
    releaseRoot: appState?.latestFinalPackProjection?.releaseRoot,
    artifactRoot: appState?.latestFinalPackProjection?.artifactRoot || artifactRoot,
    fallbackArtifactRoot: artifactFallback,
  });
  const mptextRoot = resolveMptextArchiveRoot({
    archiveRoot: appState?.latestArchiveState?.sources?.archiveRoot?.path
      || appState?.latestAuditProjection?.archiveRoot
      || archiveRoot,
    fallback: mptextFallback,
  });

  return {
    discoveryRoot,
    archiveRoot,
    artifactRoot,
    markdownMirrorRoot,
    releaseRoot,
    mptextRoot,
  };
}

export function createPcuiRootProfileController({
  appState,
  getInputPath = () => "",
  getOutputPath = () => "",
  setInputPath = () => {},
  setOutputPath = () => {},
  onRootScopedStateCleared = () => {},
  onProjectionStateCleared = () => {},
  defaults = {},
} = {}) {
  function getRoots() {
    return resolvePcuiRootProfile({
      appState,
      inputPath: getInputPath(),
      outputPath: getOutputPath(),
      defaults,
    });
  }

  function syncDetectedRootsToInputs() {
    let changed = false;
    if (!readText(getInputPath) && appState?.latestCollectState?.sources?.rootDir?.exists) {
      setInputPath(appState.latestCollectState.sources.rootDir.path);
      changed = true;
    }
    if (!readText(getOutputPath) && hasDetectedProcessRoot(appState)) {
      setOutputPath(appState.latestProcessState.sources.outRoot.path);
      changed = true;
    }
    return { changed, roots: getRoots() };
  }

  function clearRootScopedState(reason = "root-profile-change") {
    appState?.clearRootScopedState?.();
    const roots = getRoots();
    onRootScopedStateCleared({ reason, roots });
    return roots;
  }

  function clearProjectionState(workspace, reason = "projection-read-failed") {
    if (workspace === "task-bus") {
      appState.latestSnapshot = null;
      appState.selectedTaskItemPath = "";
    } else if (workspace === "collect") {
      appState.latestCollectState = null;
      appState.latestCollectLiveAccounts = [];
      appState.selectedCollectFakeid = "";
      appState.clearMultiSelection?.("collect");
    } else if (workspace === "archive") {
      appState.latestArchiveState = null;
      appState.latestArchiveLiveRows = [];
      appState.latestAuditProjection = null;
      appState.selectedArchiveToken = "";
      appState.clearMultiSelection?.("archive");
    } else if (workspace === "process") {
      appState.latestProcessState = null;
      appState.selectedProcessItemId = "";
      appState.clearMultiSelection?.("process");
    } else if (workspace === "artifact") {
      appState.latestFinalPackProjection = null;
      appState.selectedArtifactRowKey = "";
    }
    onProjectionStateCleared({ workspace, reason, roots: getRoots() });
  }

  return {
    getRoots,
    getDiscoveryRoot: () => getRoots().discoveryRoot,
    getArchiveRoot: () => getRoots().archiveRoot,
    getArtifactRoot: () => getRoots().artifactRoot,
    getMarkdownMirrorRoot: () => getRoots().markdownMirrorRoot,
    getReleaseRoot: () => getRoots().releaseRoot,
    getMptextRoot: () => getRoots().mptextRoot,
    syncDetectedRootsToInputs,
    clearRootScopedState,
    clearProjectionState,
  };
}
