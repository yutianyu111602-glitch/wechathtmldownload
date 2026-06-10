export const PCUI_SEARCH_DEBOUNCE_MS = 160;

const EMPTY_ROWS = Object.freeze([]);

function asArray(value) {
  return Array.isArray(value) ? value : EMPTY_ROWS;
}

export function normalizeSearchText(value) {
  return String(value || "").trim().toLowerCase();
}

export function createPcuiSearchQuery({ workspace = "", filter = "all", searchText = "" } = {}) {
  const normalizedFilter = String(filter || "all");
  const normalizedSearchText = normalizeSearchText(searchText);
  return {
    workspace: String(workspace || ""),
    filter: normalizedFilter,
    searchText: normalizedSearchText,
    key: `${workspace}\u0000${normalizedFilter}\u0000${normalizedSearchText}`,
  };
}

export function createPcuiSearchIndex({
  workspace = "",
  getSearchFields = () => EMPTY_ROWS,
  matchesFilter = () => true,
} = {}) {
  const textByRow = new WeakMap();

  function getRowSearchText(row) {
    if (!row || (typeof row !== "object" && typeof row !== "function")) {
      return normalizeSearchText(row);
    }
    const cached = textByRow.get(row);
    if (cached !== undefined) {
      return cached;
    }
    const text = asArray(getSearchFields(row))
      .filter((value) => value !== undefined && value !== null && value !== "")
      .join(" ")
      .toLowerCase();
    textByRow.set(row, text);
    return text;
  }

  function matches(row, query = {}) {
    const normalizedQuery = createPcuiSearchQuery({ workspace, ...query });
    if (!matchesFilter(row, normalizedQuery.filter, normalizedQuery)) {
      return false;
    }
    if (!normalizedQuery.searchText) {
      return true;
    }
    return getRowSearchText(row).includes(normalizedQuery.searchText);
  }

  function filterRows(rows, query = {}) {
    const normalizedQuery = createPcuiSearchQuery({ workspace, ...query });
    const out = [];
    for (const row of asArray(rows)) {
      if (matches(row, normalizedQuery)) {
        out.push(row);
      }
    }
    return out;
  }

  return {
    getRowSearchText,
    matches,
    filterRows,
  };
}

export function createPcuiDebouncedSearch({
  delayMs = PCUI_SEARCH_DEBOUNCE_MS,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
} = {}) {
  const timers = new Map();
  const versions = new Map();

  function begin(workspace = "workspace") {
    const key = String(workspace || "workspace");
    const token = (versions.get(key) || 0) + 1;
    versions.set(key, token);
    return { workspace: key, token };
  }

  function isLatest(workspaceOrTicket, maybeToken) {
    const workspace = typeof workspaceOrTicket === "object"
      ? workspaceOrTicket.workspace
      : String(workspaceOrTicket || "workspace");
    const token = typeof workspaceOrTicket === "object" ? workspaceOrTicket.token : maybeToken;
    return versions.get(workspace) === token;
  }

  function cancel(workspace = "workspace") {
    const key = String(workspace || "workspace");
    const timer = timers.get(key);
    if (timer) {
      clearTimer(timer);
      timers.delete(key);
    }
  }

  function schedule(workspace, value, onApply) {
    const ticket = begin(workspace);
    cancel(ticket.workspace);
    const searchText = normalizeSearchText(value);
    const timer = setTimer(() => {
      timers.delete(ticket.workspace);
      if (!isLatest(ticket)) {
        return;
      }
      onApply?.({
        workspace: ticket.workspace,
        token: ticket.token,
        value,
        searchText,
      });
    }, delayMs);
    timers.set(ticket.workspace, timer);
    return ticket;
  }

  return {
    begin,
    isLatest,
    cancel,
    schedule,
  };
}
