"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export type ArchiveSceneProps = { selected: number; paused: boolean; onSelect: (layer: number) => void };

/** A continuous trefoil, split into three polished ribbons. Illustrative, not graph data. */
class MemoryCurve extends THREE.Curve<THREE.Vector3> {
  constructor() { super(); }
  getPoint(t: number, target = new THREE.Vector3()) {
    const a = t * Math.PI * 2;
    const r = 1.18 + .38 * Math.cos(3 * a);
    return target.set(r * Math.cos(2 * a), r * Math.sin(2 * a), .52 * Math.sin(3 * a));
  }
}

function ribbon(curve: MemoryCurve, offset: number) {
  const segments = 280, sides = 20;
  const frames = curve.computeFrenetFrames(segments, true);
  const positions = [], indices = [];
  for (let i = 0; i <= segments; i++) {
    const center = curve.getPointAt(i / segments);
    for (let j = 0; j <= sides; j++) {
      const a = j / sides * Math.PI * 2;
      const p = center.clone()
        .addScaledVector(frames.normals[i], Math.cos(a) * .17)
        .addScaledVector(frames.binormals[i], offset + Math.sin(a) * .092);
      positions.push(p.x, p.y, p.z);
      if (i < segments && j < sides) {
        const k = i * (sides + 1) + j;
        indices.push(k, k + sides + 1, k + 1, k + 1, k + sides + 1, k + sides + 2);
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

export default function ArchiveScene({ selected, paused, onSelect }: ArchiveSceneProps) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef({ selected, paused, onSelect });
  const [failed, setFailed] = useState(false);
  useEffect(() => { live.current = { selected, paused, onSelect }; }, [selected, paused, onSelect]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      if (new URLSearchParams(location.search).has("no3d")) throw new Error("Static view requested");
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" });
    } catch {
      queueMicrotask(() => setFailed(true));
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.setClearColor(0x000000, 0);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    renderer.domElement.setAttribute("aria-hidden", "true");
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, .1, 30);
    camera.position.set(0, 0, 7);
    const pmrem = new THREE.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    const environment = pmrem.fromScene(room, .025);
    scene.environment = environment.texture;
    scene.environmentIntensity = 1.3;
    const sculpture = new THREE.Group();
    sculpture.rotation.set(.38, -.34, -.35);
    scene.add(sculpture);
    const key = new THREE.DirectionalLight(0xf8f7f2, 3);
    key.position.set(-3, 4, 5); scene.add(key);
    const rim = new THREE.DirectionalLight(0xffaa78, 1.5);
    rim.position.set(4, -1, 2); scene.add(rim);
    const fill = new THREE.DirectionalLight(0xb2c3e3, 1);
    fill.position.set(-5, -1, -3); scene.add(fill);
    const curve = new MemoryCurve();
    const materials: THREE.MeshPhysicalMaterial[] = [];
    const meshes: THREE.Mesh[] = [];
    for (let i = 0; i < 3; i++) {
      const mat = new THREE.MeshPhysicalMaterial({ color: 0xc5cbd5, metalness: 1, roughness: .18, clearcoat: 1, clearcoatRoughness: .1 });
      materials.push(mat);
      const mesh = new THREE.Mesh(ribbon(curve, (i - 1) * .205), mat);
      mesh.userData.layer = i;
      meshes.push(mesh); sculpture.add(mesh);
    }
    let visible = true, frame = 0, disposed = false, last = 0, drift = 0;
    let dragging = false, moved = false, downX = 0, downY = 0, rotationX = .38, rotationY = -.34;
    const pointer = new THREE.Vector2();
    const raycaster = new THREE.Raycaster();
    const draw = (time: number) => {
      frame = 0;
      if (!visible || document.hidden || disposed) return;
      const delta = Math.min((time - last) / 1000, .05); last = time;
      if (!live.current.paused && !dragging) drift += delta * .22;
      sculpture.rotation.x = rotationX + Math.sin(drift * .7) * .12;
      sculpture.rotation.y = rotationY + drift;
      sculpture.position.y = Math.sin(drift * 1.4) * .065;
      for (let i = 0; i < materials.length; i++) {
        materials[i].color.setHex(live.current.selected === i ? 0xd5a481 : 0xc1c9d5);
      }
      renderer.render(scene, camera);
      if (!live.current.paused) frame = requestAnimationFrame(draw);
    };
    const wake = () => { if (!frame && !disposed) frame = requestAnimationFrame(draw); };
    const resize = new ResizeObserver(() => {
      const { width, height } = el.getBoundingClientRect();
      renderer.setSize(width, height);
      camera.aspect = width / Math.max(height, 1);
      camera.position.z = camera.aspect < 1 ? 7.1 / camera.aspect : 7.1;
      camera.updateProjectionMatrix(); wake();
    });
    resize.observe(el);
    const intersection = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) wake(); else { cancelAnimationFrame(frame); frame = 0; }
    });
    intersection.observe(el);
    const down = (event: PointerEvent) => {
      // Leave touch scrolling to the page; mouse/pen can explore the object.
      if (event.pointerType === "touch") return;
      dragging = true; moved = false; downX = event.clientX; downY = event.clientY;
      el.setPointerCapture(event.pointerId);
    };
    const move = (event: PointerEvent) => {
      if (!dragging) return;
      const dx = event.clientX - downX, dy = event.clientY - downY;
      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
      rotationY += dx * .008; rotationX += dy * .008;
      downX = event.clientX; downY = event.clientY; wake();
    };
    const up = (event: PointerEvent) => {
      dragging = false;
      if (el.hasPointerCapture(event.pointerId)) el.releasePointerCapture(event.pointerId);
      if (!moved) {
        const rect = el.getBoundingClientRect();
        pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObjects(meshes, false)[0];
        if (hit) live.current.onSelect(hit.object.userData.layer);
      }
      moved = false; wake();
    };
    const cancel = () => { dragging = false; moved = false; wake(); };
    const contextLost = (event: Event) => { event.preventDefault(); setFailed(true); cancelAnimationFrame(frame); };
    el.addEventListener("pointerdown", down); el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up); el.addEventListener("pointercancel", cancel);
    renderer.domElement.addEventListener("webglcontextlost", contextLost);
    document.addEventListener("visibilitychange", wake);
    el.addEventListener("archive-update", wake); wake();
    return () => {
      disposed = true; cancelAnimationFrame(frame); resize.disconnect(); intersection.disconnect();
      el.removeEventListener("pointerdown", down); el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", cancel);
      el.removeEventListener("archive-update", wake);
      document.removeEventListener("visibilitychange", wake);
      renderer.domElement.removeEventListener("webglcontextlost", contextLost);
      meshes.forEach(m => m.geometry.dispose()); materials.forEach(m => m.dispose());
      environment.dispose(); room.dispose(); pmrem.dispose(); renderer.dispose(); renderer.domElement.remove();
    };
  }, []);
  useEffect(() => { host.current?.dispatchEvent(new Event("archive-update")); }, [selected, paused]);
  return <div className="archive-webgl" ref={host} data-renderer={failed ? "fallback" : "webgl"}>
    {failed && <div className="archive-fallback" role="img" aria-label="Three connected metal loops. Static illustration; use the layer buttons to explore."><svg viewBox="0 0 600 520" aria-hidden="true"><defs><linearGradient id="silver" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#eff0f1" /><stop offset=".25" stopColor="#555e6c" /><stop offset=".5" stopColor="#e7e9ed" /><stop offset=".7" stopColor="#414750" /><stop offset="1" stopColor="#a9b2c0" /></linearGradient><linearGradient id="copper"><stop stopColor="#714932" /><stop offset=".4" stopColor="#f0be90" /><stop offset=".6" stopColor="#c08156" /><stop offset="1" stopColor="#593823" /></linearGradient></defs><g fill="none" stroke="url(#silver)" strokeWidth="32"><ellipse cx="300" cy="235" rx="95" ry="165" transform="rotate(-32 300 235)" /><ellipse cx="300" cy="255" rx="95" ry="165" transform="rotate(32 300 255)" /><ellipse cx="300" cy="270" rx="100" ry="167" transform="rotate(90 300 270)" stroke="url(#copper)" strokeWidth="24" /></g></svg></div>}
  </div>;
}
