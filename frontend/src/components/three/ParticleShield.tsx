import { useEffect, useRef } from "react";
import {
  AdditiveBlending, BufferGeometry, Color, Float32BufferAttribute, PerspectiveCamera, Points,
  PointsMaterial, Scene, WebGLRenderer,
} from "three";

// Decorative only: a slow-swaying shield made of points, for the login and pitch
// surfaces. Never rendered inside the working app, never blocks input, and does
// nothing (leaves the parent's own background) if WebGL is unavailable.
// ponytail: fixed point count, halved on small screens; no adaptive frame-time
// degrade — add one if a low-end GPU ever reports jank.

const inside = (x: number, y: number) => {
  if (y > 0.95 || y < -1) return false;
  const half = y >= -0.1 ? 0.8 : 0.8 * Math.sqrt(Math.max(0, (y + 1) / 0.9));
  return Math.abs(x) <= half;
};

export default function ParticleShield({ className }: { className?: string }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ alpha: true, antialias: true });
    } catch {
      return; // no WebGL: the parent's plain background is the fallback
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);

    const scene = new Scene();
    const camera = new PerspectiveCamera(40, 1, 0.1, 20);
    camera.position.z = 4.2;

    const count = window.innerWidth < 760 ? 2500 : 5000;
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 3);
    const top = new Color("#9db2ff"), bottom = new Color("#3454d1"), c = new Color();
    for (let i = 0; i < count; ) {
      const x = Math.random() * 1.6 - 0.8, y = Math.random() * 1.95 - 1;
      if (!inside(x, y)) continue;
      pos.set([x, y, (Math.random() - 0.5) * 0.25], i * 3);
      c.copy(bottom).lerp(top, (y + 1) / 1.95);
      col.set([c.r, c.g, c.b], i * 3);
      i++;
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new Float32BufferAttribute(pos, 3));
    geometry.setAttribute("color", new Float32BufferAttribute(col, 3));
    const material = new PointsMaterial({
      size: 0.028, vertexColors: true, transparent: true, opacity: 0.85, blending: AdditiveBlending, depthWrite: false,
    });
    const shield = new Points(geometry, material);
    scene.add(shield);

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      if (!w || !h) return;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();

    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    const draw = (t: number) => {
      shield.rotation.y = Math.sin(t / 4000) * 0.4;
      shield.rotation.x = Math.sin(t / 5500) * 0.08;
      renderer.render(scene, camera);
      if (!still) frame = requestAnimationFrame(draw);
    };
    const start = () => { if (!frame) frame = requestAnimationFrame(draw); };
    const stop = () => { cancelAnimationFrame(frame); frame = 0; };
    const onVisibility = () => (document.hidden ? stop() : !still && start());
    draw(0); // reduced motion: this one frame is the whole picture
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      observer.disconnect();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={host} className={className} aria-hidden="true" />;
}
