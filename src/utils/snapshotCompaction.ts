const DEFAULT_ITEM_LIMIT = 500;

export interface SnapshotCompactionMeta {
  itemCount?: number;
  itemLimit?: number;
  itemsTruncated?: boolean;
}

export interface SnapshotItemLike {
  inputPath?: string;
  status?: string;
  startedAt?: string;
  endedAt?: string;
}

export function getSnapshotItemLimit(): number {
  const configured = Number(process.env.WECHAT_BATCH_SNAPSHOT_ITEM_LIMIT);
  if (Number.isFinite(configured) && configured > 0) {
    return Math.floor(configured);
  }
  return DEFAULT_ITEM_LIMIT;
}

function addIndex(
  indexes: Set<number>,
  index: number,
  limit: number,
): boolean {
  if (index < 0 || indexes.size >= limit) {
    return false;
  }
  indexes.add(index);
  return indexes.size < limit;
}

function addByStatus<T extends SnapshotItemLike>(
  items: T[],
  indexes: Set<number>,
  statuses: Set<string>,
  limit: number,
  direction: "forward" | "backward",
): void {
  if (indexes.size >= limit) {
    return;
  }

  if (direction === "forward") {
    for (let index = 0; index < items.length && indexes.size < limit; index += 1) {
      const status = items[index]?.status || "";
      if (statuses.has(status)) {
        addIndex(indexes, index, limit);
      }
    }
    return;
  }

  for (let index = items.length - 1; index >= 0 && indexes.size < limit; index -= 1) {
    const status = items[index]?.status || "";
    if (statuses.has(status)) {
      addIndex(indexes, index, limit);
    }
  }
}

export function compactItems<T extends SnapshotItemLike>(
  items: T[],
  options: {
    currentFile?: string;
    limit?: number;
  } = {},
): {
  items: T[];
  itemCount: number;
  itemLimit: number;
  itemsTruncated: boolean;
} {
  const itemLimit = Math.max(1, Math.floor(options.limit ?? getSnapshotItemLimit()));
  if (items.length <= itemLimit) {
    return {
      items,
      itemCount: items.length,
      itemLimit,
      itemsTruncated: false,
    };
  }

  const selected = new Set<number>();
  const currentFile = options.currentFile || "";
  if (currentFile) {
    addIndex(
      selected,
      items.findIndex((item) => item.inputPath === currentFile),
      itemLimit,
    );
  }

  addByStatus(items, selected, new Set(["running"]), itemLimit, "forward");
  addByStatus(
    items,
    selected,
    new Set(["failed", "cancelled"]),
    itemLimit,
    "backward",
  );
  addByStatus(
    items,
    selected,
    new Set(["succeeded", "skipped", "deferred", "completed"]),
    itemLimit,
    "backward",
  );
  addByStatus(items, selected, new Set(["queued"]), itemLimit, "forward");

  const compacted = Array.from(selected)
    .sort((left, right) => left - right)
    .map((index) => items[index])
    .filter((item): item is T => Boolean(item));

  return {
    items: compacted,
    itemCount: items.length,
    itemLimit,
    itemsTruncated: true,
  };
}

export function compactSnapshotItems<
  TSnapshot extends { items: TItem[]; currentFile?: string },
  TItem extends SnapshotItemLike,
>(snapshot: TSnapshot): TSnapshot & SnapshotCompactionMeta {
  const compacted = compactItems(snapshot.items, {
    currentFile: snapshot.currentFile,
  });
  if (!compacted.itemsTruncated) {
    return {
      ...snapshot,
      itemCount: compacted.itemCount,
      itemLimit: compacted.itemLimit,
      itemsTruncated: false,
    };
  }
  return {
    ...snapshot,
    items: compacted.items,
    itemCount: compacted.itemCount,
    itemLimit: compacted.itemLimit,
    itemsTruncated: true,
  };
}
