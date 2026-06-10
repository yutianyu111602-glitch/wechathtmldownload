const DEFAULT_STATE = {
  latestSnapshot: null,
  latestCollectState: null,
  latestCollectLiveAccounts: [],
  latestArchiveState: null,
  latestArchiveLiveRows: [],
  latestProcessState: null,
  latestAuditProjection: null,
  latestFinalPackProjection: null,
  latestMptextStatus: null,
  isRunning: false,
  activeWorkspace: "task-bus",
  activeConsole: "activity",
  cancellationRequested: false,
  taskBusFilter: "all",
  taskBusSearchText: "",
  processFilter: "all",
  processMode: "chain",
  processSearchText: "",
  collectFilter: "all",
  collectSearchText: "",
  archiveFilter: "all",
  archiveSearchText: "",
  artifactFilter: "all",
  artifactSearchText: "",
  selectedTaskItemPath: "",
  selectedCollectFakeid: "",
  selectedArchiveToken: "",
  selectedProcessItemId: "",
  selectedArtifactRowKey: "",
  selectedCollectFakeids: new Set(),
  selectedArchiveTokens: new Set(),
  selectedProcessItemIds: new Set(),
  lastSelectedCollectIndex: -1,
  lastSelectedArchiveIndex: -1,
  lastSelectedProcessIndex: -1,
  isConsoleCollapsed: false,
  currentFocusArea: 0,
};

const STATE_KEYS = Object.keys(DEFAULT_STATE);
const SEARCH_KEYS_BY_WORKSPACE = {
  "task-bus": "taskBusSearchText",
  collect: "collectSearchText",
  archive: "archiveSearchText",
  process: "processSearchText",
  artifact: "artifactSearchText",
};
const FILTER_KEYS_BY_WORKSPACE = {
  "task-bus": "taskBusFilter",
  collect: "collectFilter",
  archive: "archiveFilter",
  process: "processFilter",
  artifact: "artifactFilter",
};
const SELECTION_KEY_BY_WORKSPACE = {
  "task-bus": "selectedTaskItemPath",
  collect: "selectedCollectFakeid",
  archive: "selectedArchiveToken",
  process: "selectedProcessItemId",
  artifact: "selectedArtifactRowKey",
};
const MULTI_SELECTION_KEY_BY_WORKSPACE = {
  collect: "selectedCollectFakeids",
  archive: "selectedArchiveTokens",
  process: "selectedProcessItemIds",
};
const LAST_SELECTED_INDEX_KEY_BY_WORKSPACE = {
  collect: "lastSelectedCollectIndex",
  archive: "lastSelectedArchiveIndex",
  process: "lastSelectedProcessIndex",
};
const PROCESS_MODES = new Set(["chain", "llm", "downstream"]);

function cloneValue(value) {
  if (value instanceof Set) {
    return new Set(value);
  }
  if (Array.isArray(value)) {
    return [...value];
  }
  return value;
}

function createInitialState(initial) {
  const state = {};
  for (const key of STATE_KEYS) {
    state[key] = cloneValue(DEFAULT_STATE[key]);
  }
  for (const [key, value] of Object.entries(initial || {})) {
    if (!STATE_KEYS.includes(key)) {
      continue;
    }
    state[key] = DEFAULT_STATE[key] instanceof Set ? new Set(value || []) : cloneValue(value);
  }
  return state;
}

function normalizeProcessMode(mode) {
  return PROCESS_MODES.has(mode) ? mode : DEFAULT_STATE.processMode;
}

export function createPcuiAppState(initial = {}) {
  const state = createInitialState(initial);
  const api = {
    getStateSnapshot() {
      const snapshot = {};
      for (const key of STATE_KEYS) {
        snapshot[key] = cloneValue(state[key]);
      }
      return snapshot;
    },
    applyPersistedState(persisted) {
      if (!persisted) {
        return;
      }
      for (const key of [
        "activeWorkspace",
        "activeConsole",
        "isConsoleCollapsed",
        "taskBusFilter",
        "collectFilter",
        "archiveFilter",
        "processFilter",
        "artifactFilter",
        "taskBusSearchText",
        "collectSearchText",
        "archiveSearchText",
        "processSearchText",
        "artifactSearchText",
      ]) {
        if (persisted[key] !== undefined) {
          state[key] = persisted[key];
        }
      }
      if (persisted.processMode !== undefined) {
        state.processMode = normalizeProcessMode(persisted.processMode);
      }
    },
    toPersistedState(fields = {}) {
      return {
        ...fields,
        activeWorkspace: state.activeWorkspace,
        activeConsole: state.activeConsole,
        isConsoleCollapsed: state.isConsoleCollapsed,
        taskBusFilter: state.taskBusFilter,
        collectFilter: state.collectFilter,
        archiveFilter: state.archiveFilter,
        processFilter: state.processFilter,
        processMode: state.processMode,
        artifactFilter: state.artifactFilter,
        taskBusSearchText: state.taskBusSearchText,
        collectSearchText: state.collectSearchText,
        archiveSearchText: state.archiveSearchText,
        processSearchText: state.processSearchText,
        artifactSearchText: state.artifactSearchText,
      };
    },
    setWorkspace(workspace, options = {}) {
      state.activeWorkspace = workspace || DEFAULT_STATE.activeWorkspace;
      if (options.clearMultiSelection) {
        this.clearAllMultiSelections();
      }
      if (options.clearSelection) {
        this.clearAllSelections();
      }
      return state.activeWorkspace;
    },
    setConsole(consoleName) {
      state.activeConsole = consoleName || DEFAULT_STATE.activeConsole;
      return state.activeConsole;
    },
    setProcessMode(mode) {
      state.processMode = normalizeProcessMode(mode);
      return state.processMode;
    },
    getSearchText(workspace = state.activeWorkspace) {
      return state[SEARCH_KEYS_BY_WORKSPACE[workspace] || "taskBusSearchText"];
    },
    setSearchText(workspace, value) {
      const key = SEARCH_KEYS_BY_WORKSPACE[workspace] || "taskBusSearchText";
      state[key] = String(value || "").trim().toLowerCase();
      return state[key];
    },
    getFilter(workspace = state.activeWorkspace) {
      return state[FILTER_KEYS_BY_WORKSPACE[workspace] || "taskBusFilter"];
    },
    setFilter(workspace, value) {
      const key = FILTER_KEYS_BY_WORKSPACE[workspace] || "taskBusFilter";
      state[key] = value || "all";
      return state[key];
    },
    getSelection(workspace = state.activeWorkspace) {
      return state[SELECTION_KEY_BY_WORKSPACE[workspace] || "selectedTaskItemPath"];
    },
    setSelection(workspace, value) {
      const key = SELECTION_KEY_BY_WORKSPACE[workspace] || "selectedTaskItemPath";
      state[key] = value || "";
      return state[key];
    },
    clearSelection(workspace = state.activeWorkspace) {
      this.setSelection(workspace, "");
    },
    clearAllSelections() {
      for (const key of Object.values(SELECTION_KEY_BY_WORKSPACE)) {
        state[key] = "";
      }
    },
    getMultiSelection(workspace) {
      return state[MULTI_SELECTION_KEY_BY_WORKSPACE[workspace]] || new Set();
    },
    clearMultiSelection(workspace) {
      const key = MULTI_SELECTION_KEY_BY_WORKSPACE[workspace];
      if (key) {
        state[key].clear();
      }
      const indexKey = LAST_SELECTED_INDEX_KEY_BY_WORKSPACE[workspace];
      if (indexKey) {
        state[indexKey] = -1;
      }
    },
    clearAllMultiSelections() {
      for (const workspace of Object.keys(MULTI_SELECTION_KEY_BY_WORKSPACE)) {
        this.clearMultiSelection(workspace);
      }
    },
    clearRootScopedState() {
      state.latestSnapshot = null;
      state.latestCollectState = null;
      state.latestCollectLiveAccounts = [];
      state.latestArchiveState = null;
      state.latestArchiveLiveRows = [];
      state.latestProcessState = null;
      state.latestAuditProjection = null;
      state.latestFinalPackProjection = null;
      state.latestMptextStatus = null;
      this.clearAllSelections();
      this.clearAllMultiSelections();
    },
  };

  for (const key of STATE_KEYS) {
    Object.defineProperty(api, key, {
      enumerable: true,
      get: () => state[key],
      set: (value) => {
        state[key] = DEFAULT_STATE[key] instanceof Set ? new Set(value || []) : value;
      },
    });
  }

  return api;
}
