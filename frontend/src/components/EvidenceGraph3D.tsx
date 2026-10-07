import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { VERDICT_COLOR, type GraphEdge, type GraphNode } from "../lib/graph";

// The product's central claim, drawn: one artefact in the middle, wired out to
// every control it satisfies, across every framework ring at once. A table can
// say "7 links"; this shows the fan-out, and where it turns red.

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  focus: string | null;              // a node id: it and its neighbours stay lit
  accent: string;
  onHover: (id: string | null) => void;
  onPick: (node: GraphNode) => void;
};

export default function EvidenceGraph3D({ nodes, edges, focus, accent, onHover, onPick }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef({ focus, onHover, onPick });
  live.current = { focus, onHover, onPick };

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // No WebGL (disabled or blocked): say so in place of the graph instead of throwing,
    // which would blank the whole app.
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      el.textContent = "The 3D evidence map needs WebGL, which this browser has turned off for this site.";
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer();
    labels.domElement.className = "graph-labels";
    el.appendChild(labels.domElement);

    const scene = new THREE.Scene();
    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(4, 10, 6);
    scene.add(sun);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 200);
    camera.position.set(0, 0.62, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.autoRotate = !reduced;
    controls.autoRotateSpeed = 0.35;
    controls.minDistance = 5;
    controls.maxDistance = 80;

    // ---- layout: frameworks on an outer ring, their controls clustered on a
    // shell around each, evidence floating above the centre.
    const frameworks = nodes.filter((n) => n.kind === "framework");
    const pos = new Map<string, THREE.Vector3>();
    const R = Math.max(5, frameworks.length * 1.1);
    frameworks.forEach((f, i) => {
      const a = (i / frameworks.length) * Math.PI * 2;
      pos.set(f.id, new THREE.Vector3(Math.cos(a) * R, 0, Math.sin(a) * R));
    });
    for (const f of frameworks) {
      const members = nodes.filter((n) => n.kind === "control" && n.framework === f.id);
      const centre = pos.get(f.id)!;
      members.forEach((c, i) => {
        // Fibonacci shell: even spacing however many controls a framework has.
        const k = members.length;
        const y = k === 1 ? 0 : 1 - (i / (k - 1)) * 2;
        const r = Math.sqrt(1 - y * y);
        const th = i * 2.399963;
        const shell = 1.1 + Math.min(k, 30) * 0.02;
        pos.set(c.id, centre.clone().add(new THREE.Vector3(Math.cos(th) * r * shell, y * shell, Math.sin(th) * r * shell)));
      });
    }
    const evidence = nodes.filter((n) => n.kind === "evidence");
    evidence.forEach((e, i) => {
      const a = (i / Math.max(1, evidence.length)) * Math.PI * 2;
      const rr = evidence.length === 1 ? 0 : Math.min(2.4, 0.6 + evidence.length * 0.15);
      pos.set(e.id, new THREE.Vector3(Math.cos(a) * rr, 2.6 + (i % 3) * 0.35, Math.sin(a) * rr));
    });

    // ---- meshes
    const pickables: THREE.Mesh[] = [];
    const meshOf = new Map<string, THREE.Mesh>();
    const baseColor = new Map<string, THREE.Color>();
    const labelOf = new Map<string, HTMLDivElement>();
    const accentColor = new THREE.Color(accent);

    const geo = {
      framework: new THREE.TorusGeometry(0.55, 0.07, 12, 48),
      control: new THREE.SphereGeometry(0.16, 16, 12),
      evidence: new THREE.OctahedronGeometry(0.34, 0),
    };

    for (const n of nodes) {
      const p = pos.get(n.id);
      if (!p) continue;
      let color: THREE.Color;
      let mat: THREE.MeshStandardMaterial;
      if (n.kind === "framework") {
        // Neutral, so a ring never reads as a verdict colour.
        color = new THREE.Color(0xc9cff0);
        mat = new THREE.MeshStandardMaterial({ color, emissive: accentColor, emissiveIntensity: 0.3, roughness: 0.4 });
      } else if (n.kind === "control") {
        color = new THREE.Color(VERDICT_COLOR[n.verdict ?? "NONE"] ?? VERDICT_COLOR.NONE);
        mat = new THREE.MeshStandardMaterial({ color, roughness: 0.5, wireframe: n.verdict === null, transparent: true });
      } else {
        color = new THREE.Color(0xf5f7ff);
        mat = new THREE.MeshStandardMaterial({ color, emissive: accentColor, emissiveIntensity: 0.25, roughness: 0.25, metalness: 0.2 });
      }
      const mesh = new THREE.Mesh(geo[n.kind], mat);
      mesh.position.copy(p);
      if (n.kind === "framework") mesh.rotation.x = Math.PI / 2;
      if (n.kind === "evidence") mesh.scale.setScalar(0.8 + Math.min(n.links, 12) * 0.06);
      mesh.userData.id = n.id;
      scene.add(mesh);
      pickables.push(mesh);
      meshOf.set(n.id, mesh);
      baseColor.set(n.id, color);

      if (n.kind !== "control") {
        const div = document.createElement("div");
        div.className = `graph-label graph-label--${n.kind}`;
        div.textContent = n.label;
        const obj = new CSS2DObject(div);
        obj.position.copy(p).add(new THREE.Vector3(0, n.kind === "framework" ? -0.95 : 0.6, 0));
        scene.add(obj);
        labelOf.set(n.id, div);
      }
    }

    // ---- edges: a gentle arc from artefact down to control, coloured by verdict
    const neighbours = new Map<string, Set<string>>();
    const link = (a: string, b: string) => {
      if (!neighbours.has(a)) neighbours.set(a, new Set());
      neighbours.get(a)!.add(b);
    };
    const edgeObjs: { line: THREE.Line; from: string; to: string; fw: string }[] = [];
    const controlFw = new Map(nodes.filter((n) => n.kind === "control").map((n) => [n.id, (n as { framework: string }).framework]));
    for (const e of edges) {
      const a = pos.get(e.from);
      const b = pos.get(e.to);
      if (!a || !b) continue;
      const mid = a.clone().lerp(b, 0.5).add(new THREE.Vector3(0, 1.4, 0));
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(curve.getPoints(28)),
        new THREE.LineBasicMaterial({ color: VERDICT_COLOR[e.verdict] ?? VERDICT_COLOR.NONE, transparent: true, opacity: 0.55 }),
      );
      scene.add(line);
      const fw = controlFw.get(e.to) ?? "";
      edgeObjs.push({ line, from: e.from, to: e.to, fw });
      link(e.from, e.to); link(e.to, e.from); link(e.from, fw); link(fw, e.from);
    }
    for (const n of nodes) if (n.kind === "control") { link(n.framework, n.id); link(n.id, n.framework); }

    // ---- sizing
    const resize = () => {
      const w = el.clientWidth || 1;
      const h = el.clientHeight || 1;
      renderer.setSize(w, h);
      labels.setSize(w, h);
      camera.aspect = w / h;
      // Frame the whole ring of frameworks, whichever axis is tighter.
      const half = THREE.MathUtils.degToRad(camera.fov / 2);
      const fit = Math.min(half, Math.atan(Math.tan(half) * camera.aspect));
      const dist = (R + 2.2) / Math.tan(fit);
      camera.position.setLength(dist);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    // ---- picking
    const ray = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let hovered: string | null = null;
    let downAt = { x: 0, y: 0 };
    const hit = (e: PointerEvent) => {
      const r = renderer.domElement.getBoundingClientRect();
      mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(mouse, camera);
      return (ray.intersectObjects(pickables)[0]?.object.userData.id as string | undefined) ?? null;
    };
    const onMove = (e: PointerEvent) => {
      const id = hit(e);
      if (id !== hovered) {
        hovered = id;
        renderer.domElement.style.cursor = id ? "pointer" : "grab";
        live.current.onHover(id);
        controls.autoRotate = !reduced && !id;
      }
    };
    const onDown = (e: PointerEvent) => { downAt = { x: e.clientX, y: e.clientY }; };
    const onUp = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 5) return; // a drag, not a click
      const id = hit(e);
      const node = id ? nodes.find((n) => n.id === id) : null;
      if (node) live.current.onPick(node);
    };
    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);

    // ---- frame loop: focus dims everything outside the focused node's neighbourhood
    const grey = new THREE.Color(0x2a2f45);
    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const f = hovered ?? live.current.focus;
      const near = f ? new Set([f, ...(neighbours.get(f) ?? [])]) : null;
      for (const [id, mesh] of meshOf) {
        const on = !near || near.has(id);
        const mat = mesh.material as THREE.MeshStandardMaterial;
        mat.color.lerp(on ? baseColor.get(id)! : grey, 0.18);
        mat.opacity = THREE.MathUtils.lerp(mat.opacity, on ? 1 : 0.35, 0.18);
        mat.transparent = true;
        const s = id === f ? 1.35 : 1;
        mesh.scale.lerp(new THREE.Vector3(s, s, s).multiplyScalar(mesh.userData.base ?? (mesh.userData.base = mesh.scale.x)), 0.2);
        const label = labelOf.get(id);
        if (label) label.style.opacity = on ? "1" : "0.25";
      }
      for (const e of edgeObjs) {
        const on = !near || (near.has(e.from) && near.has(e.to)) || e.from === f || e.to === f || e.fw === f;
        const m = e.line.material as THREE.LineBasicMaterial;
        m.opacity = THREE.MathUtils.lerp(m.opacity, on ? (f ? 0.95 : 0.5) : 0.04, 0.18);
      }
      for (const n of frameworks) meshOf.get(n.id)!.rotation.z += 0.004;
      controls.update();
      renderer.render(scene, camera);
      labels.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      controls.dispose();
      scene.traverse((o) => {
        if (o instanceof THREE.Mesh || o instanceof THREE.Line) (o.material as THREE.Material).dispose();
        if (o instanceof THREE.Line) o.geometry.dispose();
      });
      Object.values(geo).forEach((g) => g.dispose());
      renderer.dispose();
      el.innerHTML = "";
    };
  }, [nodes, edges, accent]);

  return <div ref={host} className="graph3d" />;
}
