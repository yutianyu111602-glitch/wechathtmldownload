import { useCallback, useState } from "react";
import type { GraphData } from "../lib/types";

interface UseGraphDataResult {
  data: GraphData | null;
  loading: boolean;
  error: string | null;
  fetchOverview: (project: string, lens?: string) => void;
  fetchDetail: (project: string, centerNode: string, lens?: string) => void;
}

async function fetchLayout(
  _project: string,
  lens = "b2b_universe",
  _maxNodes = 50000,
): Promise<GraphData> {
  const baseUrl = import.meta.env.BASE_URL.endsWith("/")
    ? import.meta.env.BASE_URL
    : `${import.meta.env.BASE_URL}/`;
  const lensFile = lens ? `atlas_layout.${lens}.json` : "atlas_layout.json";
  let res = await fetch(`${baseUrl}${lensFile}`, { cache: "no-cache" });
  if (!res.ok && lens !== "b2b_universe") {
    res = await fetch(`${baseUrl}atlas_layout.b2b_universe.json`, { cache: "no-cache" });
  }
  if (!res.ok) {
    res = await fetch(`${baseUrl}atlas_layout.json`, { cache: "no-cache" });
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(body.error ?? `HTTP ${res.status}`);
  }

  return res.json();
}

export function useGraphData(): UseGraphDataResult {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchOverview = useCallback(async (project: string, lens = "b2b_universe") => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchLayout(project, lens, 50000);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch layout");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchDetail = useCallback(
    async (project: string, _centerNode: string, lens = "b2b_universe") => {
      setLoading(true);
      setError(null);
      try {
        /* TODO: detail level with center_node filtering */
        const result = await fetchLayout(project, lens, 50000);
        setData(result);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to fetch layout");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return { data, loading, error, fetchOverview, fetchDetail };
}
