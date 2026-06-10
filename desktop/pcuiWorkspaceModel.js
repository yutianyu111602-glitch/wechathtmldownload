export const WORKSPACE_MODEL = Object.freeze({
  "task-bus": {
    title: "任务总线",
    objectName: "job / run",
    subtitle: "当前和最近运行批次，一行一个 job/run。",
    counterFallback: "Running 0 | Queued 0 | Failed 0 | Locked 0",
  },
  collect: {
    title: "采集与账号",
    objectName: "account",
    subtitle: "账号对象、发现结果、就绪队列和账号级错误。",
    counterFallback: "Accounts 0 | Ready 0 | Duplicate 0 | Failed 0",
  },
  archive: {
    title: "归档与下载",
    objectName: "archive bundle",
    subtitle: "归档 bundle、capture 完整度、资源本地化和 live 下载锁。",
    counterFallback: "Bundles 0 | Capturing 0 | Assets 0 | Failed 0",
  },
  process: {
    title: "处理与导出",
    objectName: "article bundle",
    subtitle: "文章处理链、LLM 输入、OCR 和 downstream 状态。",
    counterFallback: "Articles 0 | Processing 0 | LLM Ready 0 | Warnings 0",
  },
  artifact: {
    title: "产物与审查",
    objectName: "final pack row",
    subtitle: "最终 release pack 的 ready/review/blocked 质量审查。",
    counterFallback: "Packs 0 | Ready 0 | Review 0 | Blocked 0",
  },
});

export function getWorkspaceModel(workspace) {
  return WORKSPACE_MODEL[workspace] || WORKSPACE_MODEL["task-bus"];
}

export function getWorkspaceKeys() {
  return Object.keys(WORKSPACE_MODEL);
}
