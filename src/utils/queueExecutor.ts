import PQueue from "p-queue";

export interface QueueTask<T> {
  id: string;
  fn: () => Promise<T>;
  signal?: AbortSignal;
}

export interface QueueExecutorOptions {
  concurrency: number;
  timeoutMs?: number;
  failFast?: boolean;
}

export interface QueueExecutor {
  add<T>(id: string, task: () => Promise<T>, signal?: AbortSignal): Promise<T>;
  onIdle(): Promise<void>;
  clear(): void;
  get queueSize(): number;
  get pendingCount(): number;
  get isIdle(): boolean;
}

export function createQueueExecutor(options: QueueExecutorOptions): QueueExecutor {
  const queue = new PQueue({
    concurrency: Math.max(1, options.concurrency),
    timeout: options.timeoutMs,
    autoStart: true,
  });

  let failFastError: Error | null = null;

  return {
    async add<T>(id: string, task: () => Promise<T>, signal?: AbortSignal): Promise<T> {
      if (failFastError) {
        return Promise.reject(failFastError);
      }

      if (signal?.aborted) {
        return Promise.reject(new Error(`Task ${id} aborted before start`));
      }

      return queue.add(async () => {
        if (failFastError) {
          throw failFastError;
        }
        if (signal?.aborted) {
          throw new Error(`Task ${id} aborted`);
        }

        try {
          return await task();
        } catch (error) {
          if (options.failFast && !failFastError) {
            failFastError = error instanceof Error ? error : new Error(String(error));
          }
          throw error;
        }
      });
    },

    async onIdle(): Promise<void> {
      await queue.onIdle();
    },

    clear(): void {
      queue.clear();
    },

    get queueSize(): number {
      return queue.size;
    },

    get pendingCount(): number {
      return queue.pending;
    },

    get isIdle(): boolean {
      return queue.size === 0 && queue.pending === 0;
    },
  };
}
