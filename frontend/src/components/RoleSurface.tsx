import { useEffect, useRef } from "react";
import * as THREE from "three";

// The login page's canvas: a deep shade of the hovered role's colour, with a
// slow drift of lighter and darker patches so the surface feels alive without
// competing with the deck or the map. The colour eases between roles rather
// than cutting, which is what makes hovering down the deck read as a change of
// lens. One full-screen quad, one fragment shader.

const FRAG = /* glsl */ `
  precision mediump float;
  uniform vec2 uRes;
  uniform float uTime;
  uniform vec3 uColor;
  varying vec2 vUv;

  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
  }
  float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 4; i++) { v += a * noise(p); p *= 2.02; a *= 0.5; }
    return v;
  }

  void main() {
    vec2 p = vUv * vec2(uRes.x / uRes.y, 1.0);
    float t = uTime * 0.035;
    // Domain-warped noise: soft, slowly folding bands of light.
    vec2 q = vec2(fbm(p * 1.4 + t), fbm(p * 1.4 - t + 3.1));
    float n = fbm(p * 1.8 + q * 1.6 + vec2(t * 0.6, -t * 0.4));

    vec3 deep = uColor * 0.22 + vec3(0.01, 0.012, 0.025);   // the surface itself
    vec3 lift = uColor * 0.48 + vec3(0.02);                   // its highlights
    vec3 col = mix(deep, lift, smoothstep(0.35, 0.95, n) * 0.6);

    // Brighter toward the map side, darker under the deck and at the edges.
    col *= 0.78 + 0.35 * smoothstep(0.0, 1.0, vUv.x);
    float vig = smoothstep(1.25, 0.35, length(vUv - vec2(0.6, 0.5)));
    col *= 0.7 + 0.3 * vig;

    // A little grain so the gradient never bands on cheap panels.
    col += (hash(gl_FragCoord.xy + uTime) - 0.5) * 0.012;
    gl_FragColor = vec4(col, 1.0);
  }
`;

export default function RoleSurface({ color }: { color: string }) {
  const host = useRef<HTMLDivElement>(null);
  const target = useRef(new THREE.Color(color));
  target.current.set(color);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // WebGL can be disabled or blocked (Firefox asks per site; some managed browsers turn it
    // off). three.js throws then, and an uncaught throw here blanks the whole app, so the
    // decorative background simply doesn't draw. Same pattern as three/ParticleShield.tsx.
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: false, alpha: false });
    } catch {
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    el.appendChild(renderer.domElement);

    const uniforms = {
      uRes: { value: new THREE.Vector2(1, 1) },
      uTime: { value: 0 },
      uColor: { value: target.current.clone() },
    };
    const material = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
      fragmentShader: FRAG,
      depthTest: false,
      depthWrite: false,
    });
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
    const scene = new THREE.Scene();
    scene.add(quad);
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

    const resize = () => {
      const w = el.clientWidth || 1;
      const h = el.clientHeight || 1;
      renderer.setSize(w, h, false);
      uniforms.uRes.value.set(w, h);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    const clock = new THREE.Clock();
    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      if (!reduced) uniforms.uTime.value = clock.getElapsedTime();
      uniforms.uColor.value.lerp(target.current, 0.05);
      renderer.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      quad.geometry.dispose();
      material.dispose();
      renderer.dispose();
      el.innerHTML = "";
    };
  }, []);

  return <div ref={host} className="role-surface" aria-hidden />;
}
