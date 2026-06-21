import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

/* Deep-space backdrop: thousands of faint blue-white stars on a large spherical
 * shell, slowly drifting. Non-interactive (raycast disabled), additive so it
 * reads as depth/atmosphere behind the graph without stealing focus. */
export function Starfield({ count = 4000, radius = 9000 }: { count?: number; radius?: number }) {
  const ref = useRef<THREE.Points>(null);

  const geometry = useMemo(() => {
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 3);
    const c = new THREE.Color();
    for (let i = 0; i < count; i++) {
      const r = radius * (0.55 + Math.random() * 0.45);
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      pos[i * 3 + 1] = r * Math.cos(phi);
      pos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
      // mostly cool blue-white, a few warm — cluster around hue 0.55–0.66
      c.setHSL(0.55 + Math.random() * 0.12, 0.45 + Math.random() * 0.3, 0.55 + Math.random() * 0.35);
      const b = 0.25 + Math.random() * 0.75;
      col[i * 3] = c.r * b;
      col[i * 3 + 1] = c.g * b;
      col[i * 3 + 2] = c.b * b;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    return g;
  }, [count, radius]);

  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y += dt * 0.004;
  });

  return (
    <points ref={ref} geometry={geometry} frustumCulled={false} raycast={() => null}>
      <pointsMaterial
        size={7}
        sizeAttenuation
        vertexColors
        transparent
        opacity={0.85}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
        toneMapped={false}
      />
    </points>
  );
}
