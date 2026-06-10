const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wechatDesktop", {
  pickDirectory(defaultPath) {
    return ipcRenderer.invoke("dialog:pick-directory", defaultPath || "");
  },
  startBatch(payload) {
    return ipcRenderer.invoke("batch:start", payload);
  },
  cancelBatch() {
    return ipcRenderer.invoke("batch:cancel");
  },
  getLatestSnapshot() {
    return ipcRenderer.invoke("batch:get-latest-snapshot");
  },
  getCollectState(options) {
    return ipcRenderer.invoke("collect:get-state", options || {});
  },
  getArchiveState(options) {
    return ipcRenderer.invoke("archive:get-state", options || {});
  },
  openPath(filePath) {
    return ipcRenderer.invoke("app:open-path", filePath || "");
  },
  onBatchSnapshot(callback) {
    const listener = (_event, snapshot) => callback(snapshot);
    ipcRenderer.on("batch:snapshot", listener);
    return () => ipcRenderer.removeListener("batch:snapshot", listener);
  },
  onBatchError(callback) {
    const listener = (_event, message) => callback(message);
    ipcRenderer.on("batch:error", listener);
    return () => ipcRenderer.removeListener("batch:error", listener);
  },
});