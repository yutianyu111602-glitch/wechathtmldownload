import { useMemo } from "react";
import { Billboard, Text } from "@react-three/drei";
import type { GraphNode } from "../lib/types";

interface NodeLabelsProps {
  nodes: GraphNode[];
  highlightedIds: Set<number> | null;
  maxLabels?: number;
}

export function NodeLabels({
  nodes,
  highlightedIds,
  maxLabels = 55,
}: NodeLabelsProps) {
  const labeled = useMemo(() => {
    const hasHighlight = highlightedIds && highlightedIds.size > 0;

    if (hasHighlight) {
      /* Show labels for all highlighted nodes (up to limit) */
      return nodes
        .filter((n) => highlightedIds.has(n.id))
        .sort((a, b) => b.size - a.size)
        .slice(0, maxLabels);
    }

    /* No selection: show top nodes by size */
    return [...nodes].sort((a, b) => b.size - a.size).slice(0, maxLabels);
  }, [nodes, highlightedIds, maxLabels]);

  return (
    <group>
      {labeled.map((node) => (
        <Billboard
          key={node.id}
          position={[node.x, node.y + node.size * 0.9 + 4, node.z]}
          follow
        >
          <Text
            fontSize={Math.max(16, node.size * 1.2)}
            color="#e8f0f8"
            anchorX="center"
            anchorY="bottom"
            outlineWidth={0.6}
            outlineColor="#05070d"
            fillOpacity={0.96}
          >
            {node.name}
          </Text>
        </Billboard>
      ))}
    </group>
  );
}
