import { useEffect, useRef } from "react";
import * as THREE from "three";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";

// The login page's answer to "what can this person actually open?". Every
// screen in the product is a node on a ring, grouped by the job it does; the
// role you hover lights up — in its own colour — exactly the screens its
// sidebar will have, and wires them to the core. Everything else goes dark.
// Clicking a lit node signs in as that role and opens that screen directly.
// The 3D earns its place by showing reach at a glance: five roles × fifteen
// screens is a matrix nobody reads as a table.

export type Feature = { to: string; label: string; stage: string };

type Props = {
  features: Feature[];
  reachable: Set<string>;
  color: string;
  onPick: (to: string) => void;
};

const STAGE_ORDER = ["Collect", "Assess", "Act", "Assure", "Regulate"];

export default function FeatureConstellation({ features, reachable, color, onPick }: Props) {
  const host = useRef<HTMLDivElement>(null);
  // The scene is built once; hover changes only repaint it, via this ref.
  const state = useRef<{ reachable: Set<string>; color: THREE.Color; onPick: (to: string) => void }>({
    reachable, color: new THREE.Color(color), onPick,
  });
  state.current.reachable = reachable;
  state.current.color.set(color);
  state.current.onPick = onPick;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer();
    labels.domElement.className = "constellation-labels";
    el.appendChild(labels.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);

    const world = new THREE.Group();
    world.rotation.x = 0.12;
    scene.add(world);

    // Core: the one backend every role shares.
    const coreMat = new THREE.MeshBasicMaterial({ color: state.current.color.clone() });
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.38, 1), coreMat);
    const coreWire = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.62, 1),
      new THREE.MeshBasicMaterial({ color: state.current.color.clone(), wireframe: true, transparent: true, opacity: 0.35 }),
    );
    world.add(core, coreWire);

    // Screens are spaced evenly round the ring with a one-slot gap between
    // jobs, and a faint arc under each job so the ring reads as five groups.
    const R = 4.4;
    const stages = STAGE_ORDER.filter((s) => features.some((f) => f.stage === s));
    const unit = (Math.PI * 2) / (features.length + stages.length);
    const ringMat = new THREE.LineBasicMaterial({ color: 0x8892b8, transparent: true, opacity: 0.25 });

    type Node = { f: Feature; mesh: THREE.Mesh; edge: THREE.Line; label: HTMLButtonElement; pos: THREE.Vector3; phase: number };
    const nodes: Node[] = [];
    const nodeGeo = new THREE.SphereGeometry(0.12, 20, 14);

    let cursor = 0;
    stages.forEach((stage) => {
      const members = features.filter((f) => f.stage === stage);
      const start = cursor * unit;
      const end = (cursor + members.length - 1) * unit;
      cursor += members.length + 1;
      const arc = new THREE.EllipseCurve(0, 0, R, R, start - unit * 0.35, end + unit * 0.35).getPoints(24);
      world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(arc.map((p) => new THREE.Vector3(p.x, -0.3, p.y))), ringMat));

      const stageDiv = document.createElement("div");
      stageDiv.className = "constellation-stage";
      stageDiv.textContent = stage;
      const mid = (start + end) / 2;
      const stageLabel = new CSS2DObject(stageDiv);
      stageLabel.position.set(Math.cos(mid) * (R - 1.2), -0.6, Math.sin(mid) * (R - 1.2));
      world.add(stageLabel);

      members.forEach((f, mi) => {
        const a = start + mi * unit;
        const lift = mi % 2 === 0 ? 0.45 : -0.2;
        const pos = new THREE.Vector3(Math.cos(a) * R, lift, Math.sin(a) * R);
        const mesh = new THREE.Mesh(nodeGeo, new THREE.MeshBasicMaterial({ color: 0x3a4061 }));
        mesh.position.copy(pos);
        world.add(mesh);

        const edge = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), pos]),
          new THREE.LineBasicMaterial({ color: state.current.color.clone(), transparent: true, opacity: 0 }),
        );
        world.add(edge);

        const label = document.createElement("button");
        label.type = "button";
        label.className = "constellation-node";
        label.textContent = f.label;
        label.addEventListener("click", () => {
          if (state.current.reachable.has(f.to)) state.current.onPick(f.to);
        });
        const obj = new CSS2DObject(label);
        obj.position.copy(pos).add(new THREE.Vector3(0, 0.3, 0));
        world.add(obj);
        nodes.push({ f, mesh, edge, label, pos, phase: Math.random() * Math.PI * 2 });
      });
    });

    // Pulses: one bead per lit edge, travelling core → screen, so the lit set
    // reads as "reach" rather than a static highlight.
    const beadGeo = new THREE.SphereGeometry(0.06, 10, 8);
    const beads = nodes.map(() => {
      const b = new THREE.Mesh(beadGeo, new THREE.MeshBasicMaterial({ color: 0xffffff }));
      b.visible = false;
      world.add(b);
      return b;
    });

    const resize = () => {
      const w = el.clientWidth || 1;
      const h = el.clientHeight || 1;
      renderer.setSize(w, h);
      labels.setSize(w, h);
      camera.aspect = w / h;
      // Back off until the whole ring (plus its labels) fits the narrower of
      // the two field-of-view axes, so a phone shows every screen too.
      const half = THREE.MathUtils.degToRad(camera.fov / 2);
      const fitH = Math.atan(Math.tan(half) * camera.aspect);
      // Seen from above, the ring is squashed vertically to about half its width.
      const dist = Math.max((R + 1.8) / Math.tan(fitH), (R * 0.55 + 1.4) / Math.tan(half));
      camera.position.set(0, dist * 0.5, dist);
      camera.lookAt(0, 0, 0);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    // Drag to turn the ring; it drifts on its own otherwise.
    let dragging = false;
    let lastX = 0;
    let spin = 0;
    const down = (e: PointerEvent) => { dragging = true; lastX = e.clientX; };
    const move = (e: PointerEvent) => {
      if (!dragging) return;
      spin += (e.clientX - lastX) * 0.006;
      lastX = e.clientX;
    };
    const up = () => { dragging = false; };
    el.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);

    const dim = new THREE.Color(0x3a4061);
    const clock = new THREE.Clock();
    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const t = clock.getElapsedTime();
      const { reachable: lit, color: c } = state.current;
      if (!reduced && !dragging) spin += 0.0012;
      world.rotation.y = spin;
      coreMat.color.lerp(c, 0.12);
      (coreWire.material as THREE.MeshBasicMaterial).color.lerp(c, 0.12);
      coreWire.rotation.y = -t * 0.3;
      coreWire.rotation.z = t * 0.12;

      nodes.forEach((n, i) => {
        const on = lit.has(n.f.to);
        const mat = n.mesh.material as THREE.MeshBasicMaterial;
        mat.color.lerp(on ? c : dim, 0.15);
        const target = on ? 1 + Math.sin(t * 2 + n.phase) * 0.08 : 0.7;
        n.mesh.scale.setScalar(THREE.MathUtils.lerp(n.mesh.scale.x, target, 0.15));
        const em = n.edge.material as THREE.LineBasicMaterial;
        em.color.lerp(c, 0.15);
        em.opacity = THREE.MathUtils.lerp(em.opacity, on ? 0.55 : 0, 0.12);
        n.label.classList.toggle("is-on", on);
        n.label.disabled = !on;
        n.label.style.setProperty("--node", `#${c.getHexString()}`);
        const bead = beads[i];
        bead.visible = on && !reduced;
        if (bead.visible) bead.position.copy(n.pos).multiplyScalar((t * 0.45 + n.phase) % 1);
      });

      renderer.render(scene, camera);
      labels.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      el.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      scene.traverse((o) => {
        if (o instanceof THREE.Mesh || o instanceof THREE.Line) {
          o.geometry.dispose();
          (o.material as THREE.Material).dispose();
        }
      });
      renderer.dispose();
      el.innerHTML = "";
    };
    // Built once per feature list; role changes flow through `state`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [features]);

  return <div ref={host} className="constellation" aria-hidden={false} />;
}
