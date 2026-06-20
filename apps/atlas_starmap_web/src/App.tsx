import { GraphTab } from "./components/GraphTab";

const ATLAS_PROJECT = "atlas-underground-cn";

export function App() {
  return (
    <div className="h-screen flex flex-col bg-background text-foreground">
      <header className="flex items-center justify-between gap-4 px-4 sm:px-5 h-[52px] min-h-[52px] border-b border-border bg-[#071218]/95 shrink-0">
        <div className="min-w-0 flex items-center gap-3">
          <div className="w-[7px] h-[7px] rounded-full bg-primary shrink-0" />
          <div className="min-w-0">
            <h1 className="text-[13px] sm:text-[14px] font-semibold text-foreground/95 truncate">
              ATLAS 地下电子音乐星图
            </h1>
            <p className="text-[10px] text-foreground/35 truncate">
              多镜头 / 一等实体 / 证据关系
            </p>
          </div>
        </div>

        <div className="hidden sm:flex items-center gap-2 text-[10px] text-foreground/45">
          <span className="px-2 py-1 rounded border border-white/[0.06] bg-white/[0.03]">
            atlas.starmap.v2
          </span>
          <span className="px-2 py-1 rounded border border-white/[0.06] bg-white/[0.03]">
            证据驱动
          </span>
        </div>
      </header>

      <main className="flex-1 min-h-0">
        <GraphTab project={ATLAS_PROJECT} />
      </main>
    </div>
  );
}
