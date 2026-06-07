import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

// Voice-driven 3D model viewer. The bundled GLB is a fused mesh (no named parts), so this
// panel is for whole-machine orientation: drag to orbit, or say "rotate the model 30
// degrees / on the x axis / reset the view". Each command arrives as a bumped `cmd.seq`.
export interface ModelCmd {
  action: "rotate" | "set" | "reset" | "none";
  degrees?: number;
  axis?: "x" | "y" | "z";
  seq: number;
}

const MODEL_URL = "/models/cnc_milling_machine.glb";

export function ModelPanel({ cmd }: { cmd: ModelCmd }) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const modelRef = useRef<THREE.Group | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const homeRef = useRef<{ pos: THREE.Vector3; rot: THREE.Euler; target: THREE.Vector3 } | null>(null);
  const lastSeq = useRef(0);
  const angles = useRef({ x: 0, y: 0, z: 0 });
  const [loaded, setLoaded] = useState(false);
  const [angleLabel, setAngleLabel] = useState("");
  const [status, setStatus] = useState("Loading 3D model…");

  // One-time scene setup + GLB load.
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0d1117");

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(3, 5, 4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x88aaff, 0.4);
    fill.position.set(-4, 2, -3);
    scene.add(fill);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = false;
    controlsRef.current = controls;

    function resize() {
      const w = mount!.clientWidth || 1;
      const h = mount!.clientHeight || 1;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(mount);

    let raf = 0;
    const tick = () => {
      controls.update();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    tick();

    new GLTFLoader().load(
      MODEL_URL,
      (gltf) => {
        const model = gltf.scene;
        // Center + frame the model so it fills the view regardless of its native scale.
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        model.position.sub(center);
        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        const dist = maxDim * 1.9;
        camera.position.set(dist * 0.8, dist * 0.6, dist);
        camera.lookAt(0, 0, 0);
        controls.target.set(0, 0, 0);
        controls.update();
        scene.add(model);
        modelRef.current = model;
        homeRef.current = { pos: camera.position.clone(), rot: model.rotation.clone(), target: controls.target.clone() };
        setStatus("");
        setLoaded(true); // re-run the command effect so a command issued during load replays
      },
      undefined,
      (err) => {
        console.error("[FORGE] GLB load failed", err);
        setStatus("3D model failed to load.");
      },
    );

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
  }, []);

  // Apply a voice command whenever its sequence number bumps. If the GLB hasn't loaded
  // yet, DON'T consume the seq — the effect re-runs when `loaded` flips and replays it.
  useEffect(() => {
    if (cmd.seq === lastSeq.current) return;
    const model = modelRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    const home = homeRef.current;
    if (!model) return; // not loaded — replay after load via the `loaded` dep
    lastSeq.current = cmd.seq;
    const ax = cmd.axis ?? "y";
    if (cmd.action === "rotate" && model) {
      const rad = ((cmd.degrees ?? 30) * Math.PI) / 180;
      model.rotation[ax] += rad;
      angles.current[ax] = (((angles.current[ax] + (cmd.degrees ?? 30)) % 360) + 360) % 360;
    } else if (cmd.action === "set" && model && home) {
      // Absolute angle on the named axis (relative to the model's home orientation).
      const deg = cmd.degrees ?? 0;
      model.rotation[ax] = home.rot[ax] + (deg * Math.PI) / 180;
      angles.current[ax] = ((deg % 360) + 360) % 360;
    } else if (cmd.action === "reset" && model && camera && controls && home) {
      model.rotation.copy(home.rot);
      camera.position.copy(home.pos);
      controls.target.copy(home.target);
      controls.update();
      angles.current = { x: 0, y: 0, z: 0 };
    }
    const a = angles.current;
    setAngleLabel(([["X", a.x], ["Y", a.y], ["Z", a.z]] as const).filter(([, v]) => v).map(([k, v]) => `${k} ${Math.round(v)}°`).join("  "));
  }, [cmd, loaded]);

  return (
    <div className="relative h-full min-h-[280px] w-full overflow-hidden rounded bg-[#0d1117]">
      <div ref={mountRef} className="h-full w-full" />
      <div className="pointer-events-none absolute left-2 top-2 rounded bg-black/50 px-2 py-0.5 text-[10px] text-forge-muted">
        drag to orbit · “rotate 30 degrees” · “reset the view”
      </div>
      {angleLabel && (
        <div className="pointer-events-none absolute right-2 top-2 rounded bg-black/60 px-2 py-0.5 font-mono text-[11px] text-forge-accent">
          {angleLabel}
        </div>
      )}
      {status && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-forge-muted">{status}</div>
      )}
    </div>
  );
}
