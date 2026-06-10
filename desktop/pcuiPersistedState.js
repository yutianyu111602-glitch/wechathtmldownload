export const PCUI_STATE_STORAGE_KEY = "pcui_state_v1";

export function readPcuiPersistedState(storage = localStorage, key = PCUI_STATE_STORAGE_KEY) {
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function writePcuiPersistedState(state, storage = localStorage, key = PCUI_STATE_STORAGE_KEY) {
  try {
    storage.setItem(key, JSON.stringify(state));
  } catch {
    // Ignore unavailable or full storage; UI state persistence is best effort.
  }
}
