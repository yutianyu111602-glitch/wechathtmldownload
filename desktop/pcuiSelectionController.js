const SINGLE_SELECTION_KEYS = Object.freeze({
  "task-bus": "selectedTaskItemPath",
  collect: "selectedCollectFakeid",
  archive: "selectedArchiveToken",
  process: "selectedProcessItemId",
  artifact: "selectedArtifactRowKey",
});

const MULTI_SELECTION_KEYS = Object.freeze({
  collect: "selectedCollectFakeids",
  archive: "selectedArchiveTokens",
  process: "selectedProcessItemIds",
});

const LAST_INDEX_KEYS = Object.freeze({
  collect: "lastSelectedCollectIndex",
  archive: "lastSelectedArchiveIndex",
  process: "lastSelectedProcessIndex",
});

function defaultGetKey(item) {
  return item?.id || item?.key || "";
}

function asArray(items) {
  return Array.isArray(items) ? items : [];
}

export function createPcuiSelectionController({ appState } = {}) {
  function getSelectedKey(workspace) {
    return appState?.[SINGLE_SELECTION_KEYS[workspace]] || "";
  }

  function setSelectedKey(workspace, key) {
    const stateKey = SINGLE_SELECTION_KEYS[workspace];
    if (stateKey) {
      appState[stateKey] = key || "";
    }
    return key || "";
  }

  function getMultiSelection(workspace) {
    return appState?.[MULTI_SELECTION_KEYS[workspace]] || new Set();
  }

  function clearMultiSelection(workspace) {
    appState?.clearMultiSelection?.(workspace);
  }

  function ensureSelectedKey(workspace, items, getKey = defaultGetKey) {
    const rows = asArray(items);
    const currentKey = getSelectedKey(workspace);
    if (currentKey && rows.some((item) => getKey(item) === currentKey)) {
      return currentKey;
    }
    return setSelectedKey(workspace, rows[0] ? getKey(rows[0]) : "");
  }

  function findSelectedItem(workspace, items, getKey = defaultGetKey) {
    const selectedKey = getSelectedKey(workspace);
    if (!selectedKey) {
      return null;
    }
    return asArray(items).find((item) => getKey(item) === selectedKey) || null;
  }

  function isMultiSelect(workspace) {
    return getMultiSelection(workspace).size > 1;
  }

  function getMultiSelectCount(workspace) {
    return getMultiSelection(workspace).size;
  }

  function toggleMultiSelection(workspace, {
    key,
    index,
    event = {},
    items = [],
    getKey = defaultGetKey,
  } = {}) {
    const selectedSet = getMultiSelection(workspace);
    const lastIndexKey = LAST_INDEX_KEYS[workspace];
    const lastIndex = lastIndexKey ? appState[lastIndexKey] : -1;
    const rows = asArray(items);
    const isCtrl = Boolean(event.ctrlKey || event.metaKey);
    const isShift = Boolean(event.shiftKey);

    if (isShift && lastIndex >= 0) {
      const start = Math.min(lastIndex, index);
      const end = Math.max(lastIndex, index);
      for (let i = start; i <= end; i++) {
        const rowKey = getKey(rows[i]);
        if (rowKey) {
          selectedSet.add(rowKey);
        }
      }
    } else if (isCtrl) {
      if (selectedSet.has(key)) {
        selectedSet.delete(key);
      } else if (key) {
        selectedSet.add(key);
      }
    } else {
      selectedSet.clear();
      if (key) {
        selectedSet.add(key);
      }
    }

    if (lastIndexKey) {
      appState[lastIndexKey] = index;
    }
    return setSelectedKey(workspace, key);
  }

  return {
    getSelectedKey,
    setSelectedKey,
    ensureSelectedKey,
    findSelectedItem,
    getMultiSelection,
    clearMultiSelection,
    isMultiSelect,
    getMultiSelectCount,
    toggleMultiSelection,
  };
}
