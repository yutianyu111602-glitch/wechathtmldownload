const DEFAULT_FOCUS_AREAS = Object.freeze(["workspace", "inspector", "console"]);

function normalizeIndex(index, length) {
  return ((index % length) + length) % length;
}

function toArray(items) {
  return Array.from(items || []);
}

function getLowerKey(event) {
  return String(event?.key || "").toLowerCase();
}

function runAction(action, ...args) {
  if (typeof action === "function") {
    action(...args);
    return true;
  }
  return false;
}

function focusElement(element) {
  if (element && typeof element.focus === "function") {
    element.focus();
    return true;
  }
  return false;
}

function clickElement(element) {
  if (element && typeof element.click === "function") {
    element.click();
    return true;
  }
  return false;
}

function queryFirst(root, selector) {
  return typeof root?.querySelector === "function" ? root.querySelector(selector) : null;
}

export function isPcuiTextInputTarget(target) {
  if (!target) {
    return false;
  }
  const tagName = String(target.tagName || "").toLowerCase();
  if (["input", "textarea", "select"].includes(tagName)) {
    return true;
  }
  if (target.isContentEditable) {
    return true;
  }
  if (typeof target.closest === "function") {
    return Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
  }
  return false;
}

export function shouldIgnorePcuiGlobalKeyboardTarget(event) {
  return Boolean(event?.defaultPrevented || isPcuiTextInputTarget(event?.target));
}

export function handlePcuiRowActivationKeydown(event, activate) {
  if (isPcuiTextInputTarget(event?.target)) {
    return false;
  }
  if (event?.key !== "Enter" && event?.key !== " ") {
    return false;
  }
  event.preventDefault?.();
  if (typeof activate === "function") {
    activate(event);
  }
  return true;
}

export function bindPcuiRowActivation(row, activate) {
  row?.addEventListener?.("keydown", (event) => {
    handlePcuiRowActivationKeydown(event, activate);
  });
  row?.addEventListener?.("click", activate);
  return row;
}

export function createPcuiKeyboardController({
  appState,
  root = globalThis.document,
  focusAreas = DEFAULT_FOCUS_AREAS,
  refs = {},
  actions = {},
} = {}) {
  const focusAreaList = focusAreas.length ? focusAreas : DEFAULT_FOCUS_AREAS;

  function setFocusArea(index) {
    if (!appState) {
      return "";
    }
    appState.currentFocusArea = normalizeIndex(index, focusAreaList.length);
    const area = focusAreaList[appState.currentFocusArea];

    queryFirst(root, ".workspace-frame")?.classList.toggle("is-focused", area === "workspace");
    queryFirst(root, ".right-inspector")?.classList.toggle("is-focused", area === "inspector");
    refs.bottomRunConsole?.classList.toggle("is-focused", area === "console");

    if (area === "workspace") {
      return focusElement(queryFirst(root, ".workspace-panel.is-active .item-row[tabindex='0'], .workspace-panel.is-active .collect-row-v2[tabindex='0'], .workspace-panel.is-active .archive-row-v2[tabindex='0'], .workspace-panel.is-active .process-row[tabindex='0'], .workspace-panel.is-active .artifact-row[tabindex='0'], .workspace-panel.is-active button, .workspace-panel.is-active input, .nav-item.is-active")) ? area : area;
    }
    if (area === "inspector") {
      return focusElement(queryFirst(root, ".right-inspector button:not([disabled]), .right-inspector input:not([disabled]), .right-inspector [tabindex='0']")) ? area : area;
    }
    if (area === "console") {
      return focusElement(queryFirst(root, ".console-tab.is-active")) ? area : area;
    }
    return area;
  }

  function focusNextArea() {
    return setFocusArea((appState?.currentFocusArea || 0) + 1);
  }

  function handleGlobalKeydown(event) {
    if (shouldIgnorePcuiGlobalKeyboardTarget(event)) {
      return false;
    }

    const key = String(event.key || "");
    const lowerKey = getLowerKey(event);
    const accel = Boolean(event.ctrlKey || event.metaKey);

    if (accel && lowerKey === "enter") {
      event.preventDefault();
      return runAction(actions.start) || clickElement(refs.startButton);
    }

    if (key === "Escape") {
      event.preventDefault();
      return runAction(actions.stop) || clickElement(refs.stopButton);
    }

    if (accel && lowerKey === "o") {
      event.preventDefault();
      return runAction(actions.openOutput) || clickElement(refs.openOutputButton);
    }

    if (accel && lowerKey === "m") {
      event.preventDefault();
      return runAction(actions.openMarkdownMirror) || clickElement(refs.autoMdButton);
    }

    if (accel && /^[1-5]$/.test(key)) {
      event.preventDefault();
      return runAction(actions.switchWorkspaceByIndex, Number(key) - 1);
    }

    if (accel && lowerKey === "r") {
      event.preventDefault();
      return runAction(actions.refreshCurrentWorkspace);
    }

    if (key === "F6") {
      event.preventDefault();
      setFocusArea((appState?.currentFocusArea || 0) + 1);
      return true;
    }

    if (accel && event.shiftKey && key === "ArrowDown") {
      event.preventDefault();
      return runAction(actions.toggleConsoleCollapse);
    }

    return false;
  }

  function bindConsoleTabs(tabs, setConsole) {
    const tabList = toArray(tabs);
    const setConsoleAction = typeof setConsole === "function" ? setConsole : actions.setConsole;
    for (const tab of tabList) {
      tab.addEventListener("keydown", (event) => {
        if (shouldIgnorePcuiGlobalKeyboardTarget(event)) {
          return;
        }

        const currentIndex = Math.max(0, tabList.indexOf(tab));
        let nextIndex = -1;
        if (event.key === "ArrowRight" || event.key === "ArrowDown") {
          nextIndex = normalizeIndex(currentIndex + 1, tabList.length);
        } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
          nextIndex = normalizeIndex(currentIndex - 1, tabList.length);
        } else if (event.key === "Home") {
          nextIndex = 0;
        } else if (event.key === "End") {
          nextIndex = tabList.length - 1;
        }

        if (nextIndex < 0) {
          return;
        }

        event.preventDefault();
        const nextTab = tabList[nextIndex];
        if (nextTab?.dataset?.console) {
          setConsoleAction?.(nextTab.dataset.console);
        }
        focusElement(nextTab);
      });
    }
  }

  return {
    bindConsoleTabs,
    focusNextArea,
    handleGlobalKeydown,
    setFocusArea,
  };
}
