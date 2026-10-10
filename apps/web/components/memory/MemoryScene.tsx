"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

type Props = { selected: number; paused: boolean; reducedMotion: boolean };

/** An authored illustration of memory assembly, never a visualization of live records. */
export default function MemoryScene({ selected, paused, reducedMotion }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef({ selected, paused, reducedMotion });
  const wake = useRef<() => void>(() => {});
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    state.current = { selected, paused, reducedMotion };
    wake.current();
  }, [selected, paused, reducedMotion]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      if (new URLSearchParams(location.search).has("no3d")) throw new Error("Static view");
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" });
    } catch {
      queueMicrotask(() => setFailed(true));
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    renderer.setClearColor(0x000000, 0);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.25;
    renderer.domElement.setAttribute("aria-hidden", "true");
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, .1, 40);
    camera.position.set(0, 0, 9.5);
    const pmrem = new THREE.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    const environment = pmrem.fromScene(room, .03);
    scene.environment = environment.texture;
    scene.environmentIntensity = 1.5;
    const group = new THREE.Group();
    group.rotation.set(.25, -.5, -.38);
    scene.add(group);
    const key = new THREE.DirectionalLight(0xf1edff, 4);
    key.position.set(-3, 5, 6);
    const rim = new THREE.DirectionalLight(0x729aff, 5);
    rim.position.set(4, 1, -2);
    const fill = new THREE.DirectionalLight(0xbac9ff, 2);
    fill.position.set(-4, -3, 2);
    scene.add(key, rim, fill);

    const ring: THREE.Vector3[] = [];
    const step = .27;
    for (let x = -8; x <= 8; x++) {
      for (let y = -8; y <= 8; y++) {
        for (let z = -3; z <= 3; z++) {
          const p = new THREE.Vector3(x * step, y * step, z * step);
          if ((Math.hypot(p.x, p.y) - 1.36) ** 2 + p.z ** 2 < .59 ** 2) ring.push(p);
        }
      }
    }
    const count = ring.length;
    const random = (i: number) => { const v = Math.sin(i * 127.1 + 311.7) * 43758.5453; return v - Math.floor(v); };
    const side = Math.ceil(Math.cbrt(count));
    const layouts = [
      ring.map((p, i) => p.clone().multiplyScalar(1.05 + random(i) * .65).add(new THREE.Vector3((random(i + 9) - .5) * .7, (random(i + 17) - .5) * .7, (random(i + 41) - .5) * 1.8))),
      ring,
      ring.map((_, i) => new THREE.Vector3((i % side - (side - 1) / 2) * .31, (Math.floor(i / side) % side - (side - 1) / 2) * .31, (Math.floor(i / (side * side)) - (side - 1) / 2) * .31)),
    ];
    const geometry = new RoundedBoxGeometry(.238, .238, .238, 2, .021);
    const material = new THREE.MeshPhysicalMaterial({ metalness: .82, roughness: .26, clearcoat: .8 });
    const mesh = new THREE.InstancedMesh(geometry, material, count);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.frustumCulled = false;
    group.add(mesh);
    const positions = layouts[state.current.selected].map(p => p.clone().multiplyScalar(state.current.reducedMotion ? 1 : 1.12));
    const object = new THREE.Object3D();
    const color = new THREE.Color();
    for (let i = 0; i < count; i++) {
      const accent = ring[i].x > .3 && ring[i].y < .7 && ring[i].z > -.2;
      color.set(accent ? (i % 3 === 0 ? "#b1c8ff" : "#6986d5") : (i % 7 === 0 ? "#636879" : "#c6cbd7"));
      mesh.setColorAt(i, color);
    }

    let frame = 0, last = 0, time = 0, visible = true, disposed = false;
    let pointerX = 0, pointerY = 0, dragX = -.5, dragY = .25, dragging = false;
    let lastX = 0, lastY = 0, hover = -1, settled = false;
    const pointer = new THREE.Vector2();
    const raycaster = new THREE.Raycaster();
    const target = new THREE.Vector3();
    const offset = new THREE.Vector3();

    const render = (now: number) => {
      frame = 0;
      if (disposed || !visible || document.hidden) return;
      const dt = Math.min((now - last) / 1000 || .016, .05);
      last = now;
      const moving = !state.current.paused && !state.current.reducedMotion;
      if (moving) time += dt;
      const blend = state.current.reducedMotion || state.current.paused ? 1 : 1 - Math.exp(-dt * 5);
      let remaining = 0;
      for (let i = 0; i < count; i++) {
        target.copy(layouts[state.current.selected][i]);
        if (hover >= 0 && !state.current.reducedMotion && !state.current.paused) {
          offset.copy(target).sub(layouts[state.current.selected][hover]);
          const length = offset.length();
          if (length < 1.05) target.addScaledVector(offset.normalize(), (1.05 - length) * .35);
        }
        positions[i].lerp(target, blend);
        remaining += positions[i].distanceToSquared(target);
        object.position.copy(positions[i]);
        object.rotation.set(0, 0, 0);
        object.scale.setScalar(1);
        object.updateMatrix();
        mesh.setMatrixAt(i, object.matrix);
      }
      mesh.instanceMatrix.needsUpdate = true;
      group.rotation.y += (dragX + (moving ? Math.sin(time * .18) * .18 + pointerX * .13 : 0) - group.rotation.y) * blend;
      group.rotation.x += (dragY + (moving ? pointerY * .1 : 0) - group.rotation.x) * blend;
      group.position.y = Math.sin(time * .6) * .06;
      const distance = (state.current.selected === 0 ? 12 : 8.6) / Math.min(camera.aspect, 1);
      camera.position.z += (distance - camera.position.z) * blend;
      renderer.render(scene, camera);
      settled = remaining < .0001;
      if (moving || !settled) frame = requestAnimationFrame(render);
    };
    const requestRender = () => { if (!frame && !disposed) frame = requestAnimationFrame(render); };
    wake.current = requestRender;
    const resize = new ResizeObserver(() => {
      const { width, height } = el.getBoundingClientRect();
      renderer.setSize(width, height);
      camera.aspect = width / Math.max(height, 1);
      camera.position.z = (state.current.selected === 0 ? 12 : 8.6) / Math.min(camera.aspect, 1);
      camera.updateProjectionMatrix();
      requestRender();
    });
    resize.observe(el);
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) requestRender(); else { cancelAnimationFrame(frame); frame = 0; }
    });
    observer.observe(el);
    const onDown = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      el.setPointerCapture(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      const rect = el.getBoundingClientRect();
      pointerX = ((e.clientX - rect.left) / rect.width - .5) * 2;
      pointerY = ((e.clientY - rect.top) / rect.height - .5) * 2;
      if (dragging) {
        dragX += (e.clientX - lastX) * .006; dragY += (e.clientY - lastY) * .006;
        lastX = e.clientX; lastY = e.clientY;
      }
      pointer.set(pointerX, -pointerY);
      raycaster.setFromCamera(pointer, camera);
      hover = raycaster.intersectObject(mesh)[0]?.instanceId ?? -1;
      requestRender();
    };
    const onUp = (e: PointerEvent) => { dragging = false; if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId); };
    const onLeave = () => { hover = -1; pointerX = 0; pointerY = 0; requestRender(); };
    const onLost = (e: Event) => { e.preventDefault(); cancelAnimationFrame(frame); frame = 0; disposed = true; setFailed(true); };
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("pointerleave", onLeave);
    renderer.domElement.addEventListener("webglcontextlost", onLost);
    document.addEventListener("visibilitychange", requestRender);
    requestRender();
    return () => {
      disposed = true; cancelAnimationFrame(frame); wake.current = () => {};
      observer.disconnect(); resize.disconnect();
      el.removeEventListener("pointerdown", onDown); el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp); el.removeEventListener("pointercancel", onUp); el.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", requestRender);
      renderer.domElement.removeEventListener("webglcontextlost", onLost);
      mesh.dispose(); geometry.dispose(); material.dispose(); environment.dispose(); room.dispose(); pmrem.dispose(); renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div className="memory-webgl" ref={host} data-renderer={failed ? "fallback" : "webgl"}>
    {failed && <StaticMemory selected={selected} />}
  </div>;
}

function StaticMemory({ selected }: { selected: number }) {
  return <svg className="static-memory" viewBox="0 0 500 500" role="img" aria-label={["Scattered memory blocks", "Connected memory ring", "Organized memory blocks"][selected]}>
    <defs><linearGradient id="memory-metal" x2="1" y2="1"><stop stopColor="#eef0f8" /><stop offset=".45" stopColor="#9296ad" /><stop offset="1" stopColor="#434654" /></linearGradient><linearGradient id="memory-blue" x2="1" y2="1"><stop stopColor="#b1c8ff" /><stop offset="1" stopColor="#506bc2" /></linearGradient></defs>
    <g transform="translate(250 250) rotate(-25) skewY(9)">{Array.from({ length: 15 * 15 }, (_, i) => {
      const x = i % 15 - 7, y = Math.floor(i / 15) - 7, d = Math.hypot(x, y);
      if (selected !== 2 && (d < 3.3 || d > 7)) return null;
      if (selected === 2 && (Math.abs(x) > 5 || Math.abs(y) > 5)) return null;
      return <rect key={i} x={x * 24 + (selected === 0 ? Math.sin(i * 3) * 15 : 0)} y={y * 24 + (selected === 0 ? Math.cos(i * 5) * 20 : 0)} width="21" height="21" rx="3" fill={x > 1 && y < 4 ? "url(#memory-blue)" : "url(#memory-metal)"} />;
    })}</g>
  </svg>;
}
