import * as THREE from './three.module.min.js';
import { STLLoader } from './STLLoader.js';

const canvas = document.getElementById('pluto3dCanvas');
const viewport = document.getElementById('ops3dViewport');
const statusNode = document.getElementById('visual3dStatus');

const api = {
  ready: false,
  update() {},
};
window.Pluto3D = api;

if (!canvas || !viewport) {
  if (statusNode) statusNode.textContent = '3D viewport not mounted';
} else {
  try {
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x081016);
    scene.fog = new THREE.Fog(0x081016, 520, 1180);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1800);
    camera.position.set(360, 285, 460);
    camera.lookAt(0, 45, 0);

    const hemi = new THREE.HemisphereLight(0xdcefff, 0x16212a, 1.7);
    scene.add(hemi);

    const key = new THREE.DirectionalLight(0xffffff, 2.1);
    key.position.set(220, 420, 260);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    scene.add(key);

    const rim = new THREE.PointLight(0x52a8ff, 2.2, 720);
    rim.position.set(-260, 180, -260);
    scene.add(rim);

    const materials = {
      floor: new THREE.MeshStandardMaterial({ color: 0x101820, roughness: 0.92, metalness: 0.08 }),
      chassis: new THREE.MeshStandardMaterial({ color: 0xdbe7ef, roughness: 0.45, metalness: 0.18 }),
      shell: new THREE.MeshStandardMaterial({ color: 0x17212a, roughness: 0.5, metalness: 0.18 }),
      tire: new THREE.MeshStandardMaterial({ color: 0x11171d, roughness: 0.8, metalness: 0.05 }),
      arm: new THREE.MeshStandardMaterial({ color: 0x8ea3b3, roughness: 0.55, metalness: 0.2 }),
      tablet: new THREE.MeshStandardMaterial({
        color: 0x0b1015,
        roughness: 0.28,
        metalness: 0.35,
        emissive: 0x1769aa,
        emissiveIntensity: 0.18,
      }),
      face: new THREE.MeshStandardMaterial({
        color: 0x041018,
        roughness: 0.18,
        metalness: 0.08,
        emissive: 0x52a8ff,
        emissiveIntensity: 0.6,
      }),
      good: new THREE.MeshBasicMaterial({ color: 0x39d98a, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false }),
      warn: new THREE.MeshBasicMaterial({ color: 0xffc857, transparent: true, opacity: 0.27, side: THREE.DoubleSide, depthWrite: false }),
      bad: new THREE.MeshBasicMaterial({ color: 0xff5d52, transparent: true, opacity: 0.34, side: THREE.DoubleSide, depthWrite: false }),
      unknown: new THREE.MeshBasicMaterial({ color: 0x71808c, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false }),
      lineGood: new THREE.LineBasicMaterial({ color: 0x39d98a, linewidth: 2 }),
      lineWarn: new THREE.LineBasicMaterial({ color: 0xffc857, linewidth: 2 }),
      lineBad: new THREE.LineBasicMaterial({ color: 0xff5d52, linewidth: 2 }),
      blueLine: new THREE.LineBasicMaterial({ color: 0x52a8ff, linewidth: 2 }),
    };

    const floor = new THREE.Mesh(new THREE.PlaneGeometry(820, 820), materials.floor);
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);

    const grid = new THREE.GridHelper(820, 20, 0x3d5362, 0x20303b);
    grid.position.y = 0.8;
    scene.add(grid);

    const robot = new THREE.Group();
    scene.add(robot);

    const proxyBody = new THREE.Group();
    robot.add(proxyBody);

    const cadRobot = new THREE.Group();
    cadRobot.visible = false;
    robot.add(cadRobot);

    const chassis = new THREE.Mesh(new THREE.BoxGeometry(82, 38, 112), materials.chassis);
    chassis.position.y = 38;
    chassis.castShadow = true;
    proxyBody.add(chassis);

    const deck = new THREE.Mesh(new THREE.BoxGeometry(92, 12, 122), materials.shell);
    deck.position.y = 65;
    deck.castShadow = true;
    proxyBody.add(deck);

    const neck = new THREE.Mesh(new THREE.CylinderGeometry(12, 18, 38, 24), materials.arm);
    neck.position.y = 95;
    neck.castShadow = true;
    proxyBody.add(neck);

    const head = new THREE.Group();
    head.position.y = 132;
    robot.add(head);

    const tablet = new THREE.Mesh(new THREE.BoxGeometry(92, 64, 9), materials.tablet);
    tablet.position.z = -8;
    tablet.castShadow = true;
    head.add(tablet);

    const face = new THREE.Mesh(new THREE.PlaneGeometry(78, 48), materials.face);
    face.position.z = -13;
    head.add(face);

    const eyeMat = new THREE.MeshBasicMaterial({ color: 0xc8f4ff });
    const leftEye = new THREE.Mesh(new THREE.SphereGeometry(4.5, 18, 12), eyeMat);
    leftEye.position.set(-18, 7, -14.5);
    const rightEye = leftEye.clone();
    rightEye.position.x = 18;
    head.add(leftEye, rightEye);

    const mouth = new THREE.Mesh(new THREE.BoxGeometry(34, 3, 1), new THREE.MeshBasicMaterial({ color: 0xc8f4ff }));
    mouth.position.set(0, -13, -14.5);
    head.add(mouth);

    const wheelMeshes = [];
    const wheelGeo = new THREE.CylinderGeometry(19, 19, 14, 32);
    for (const x of [-52, 52]) {
      for (const z of [-38, 38]) {
        const wheel = new THREE.Mesh(wheelGeo, materials.tire);
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(x, 24, z);
        wheel.castShadow = true;
        wheelMeshes.push(wheel);
        proxyBody.add(wheel);
      }
    }

    for (const x of [-58, 58]) {
      const shoulder = new THREE.Mesh(new THREE.BoxGeometry(11, 54, 11), materials.arm);
      shoulder.position.set(x, 72, -4);
      shoulder.rotation.z = x < 0 ? -0.28 : 0.28;
      shoulder.castShadow = true;
      proxyBody.add(shoulder);
    }

    const rangeGroup = new THREE.Group();
    scene.add(rangeGroup);

    const beams = [
      { key: 'FL', angle: -34, width: 23, mesh: null, marker: null },
      { key: 'F', angle: 0, width: 18, mesh: null, marker: null },
      { key: 'FR', angle: 34, width: 23, mesh: null, marker: null },
    ];

    for (const beam of beams) {
      beam.mesh = new THREE.Mesh(new THREE.BufferGeometry(), materials.unknown);
      beam.mesh.renderOrder = 2;
      rangeGroup.add(beam.mesh);
      beam.marker = new THREE.Mesh(new THREE.SphereGeometry(7, 18, 12), new THREE.MeshBasicMaterial({ color: 0x71808c }));
      beam.marker.position.y = 5;
      rangeGroup.add(beam.marker);
    }

    const envelopeLine = new THREE.Line(new THREE.BufferGeometry(), materials.blueLine);
    envelopeLine.position.y = 3;
    scene.add(envelopeLine);

    const predictionLine = new THREE.Line(new THREE.BufferGeometry(), materials.lineGood);
    predictionLine.position.y = 8;
    scene.add(predictionLine);

    const cadWheelMeshes = [];
    const cadPartMaterial = {
      base: new THREE.MeshStandardMaterial({ color: 0xdce8ef, roughness: 0.5, metalness: 0.18 }),
      wheel: new THREE.MeshStandardMaterial({ color: 0x171d22, roughness: 0.74, metalness: 0.08 }),
      arm: new THREE.MeshStandardMaterial({ color: 0x2b343c, roughness: 0.62, metalness: 0.14 }),
    };
    const cadParts = [
      { name: 'base_link', type: 'base', origin: [0, 0, 0], rpy: [0, 0, 0], url: '/static/robot_meshes/base_link.STL' },
      { name: 'front_rightwheel', type: 'wheel', origin: [0.10031, 0.10904, -0.5136], rpy: [0, 0, -3.1416], url: '/static/robot_meshes/front_rightwheel.STL' },
      { name: 'front_leftwheel', type: 'wheel', origin: [0.10031, -0.1101, -0.5136], rpy: [0, 0, -3.1416], url: '/static/robot_meshes/front_leftwheel.STL' },
      { name: 'back_rigtwheel', type: 'wheel', origin: [-0.084446, 0.10904, -0.5136], rpy: [0, 0, -3.1416], url: '/static/robot_meshes/back_rigtwheel.STL' },
      { name: 'back_leftwheel', type: 'wheel', origin: [-0.084446, -0.11011, -0.5136], rpy: [0, 0, -3.1416], url: '/static/robot_meshes/back_leftwheel.STL' },
      { name: 'leftarm', type: 'arm', origin: [-0.00014739, -0.12106, 0.27598], rpy: [0, -0.058023, -3.1416], url: '/static/robot_meshes/leftarm.STL' },
      { name: 'rightarm', type: 'arm', origin: [0.016015, 0.12, 0.27598], rpy: [0, 0, -3.1416], url: '/static/robot_meshes/rightarm.STL' },
    ];

    const startedAt = performance.now();
    let current = {
      mode: 'BOOTSTRAP',
      stateColor: 0x52a8ff,
      speed: 0,
      heading: 0,
      sensorConfidence: 0,
      cadLoaded: false,
    };

    function rosToThreePosition([x, y, z]) {
      return new THREE.Vector3(y * 100, z * 100, -x * 100);
    }

    function rosRotationToThreeQuaternion([roll, pitch, yaw]) {
      const rosRotation = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(roll, pitch, yaw, 'XYZ'));
      const rosToThree = new THREE.Matrix4().set(
        0, 1, 0, 0,
        0, 0, 1, 0,
        -1, 0, 0, 0,
        0, 0, 0, 1,
      );
      const threeToRos = new THREE.Matrix4().copy(rosToThree).invert();
      const threeRotation = new THREE.Matrix4().multiplyMatrices(
        rosToThree,
        new THREE.Matrix4().multiplyMatrices(rosRotation, threeToRos),
      );
      return new THREE.Quaternion().setFromRotationMatrix(threeRotation);
    }

    function convertRosGeometryToThree(geometry) {
      const position = geometry.getAttribute('position');
      for (let i = 0; i < position.count; i += 1) {
        const x = position.getX(i);
        const y = position.getY(i);
        const z = position.getZ(i);
        position.setXYZ(i, y * 100, z * 100, -x * 100);
      }
      position.needsUpdate = true;
      geometry.computeVertexNormals();
      geometry.computeBoundingBox();
      geometry.computeBoundingSphere();
      return geometry;
    }

    async function loadCadRobot() {
      const loader = new STLLoader();
      try {
        const meshes = await Promise.all(cadParts.map(async (part) => {
          const geometry = convertRosGeometryToThree(await loader.loadAsync(part.url));
          const mesh = new THREE.Mesh(geometry, cadPartMaterial[part.type]);
          mesh.name = `cad_${part.name}`;
          mesh.castShadow = true;
          mesh.receiveShadow = true;
          const joint = new THREE.Group();
          joint.name = `joint_${part.name}`;
          joint.position.copy(rosToThreePosition(part.origin));
          joint.quaternion.copy(rosRotationToThreeQuaternion(part.rpy));
          joint.add(mesh);
          cadRobot.add(joint);
          if (part.type === 'wheel') cadWheelMeshes.push(mesh);
          return mesh;
        }));
        const box = new THREE.Box3().setFromObject(cadRobot);
        const center = box.getCenter(new THREE.Vector3());
        cadRobot.position.set(-center.x, -box.min.y, -center.z);
        cadRobot.visible = true;
        proxyBody.visible = false;
        head.visible = false;
        current.cadLoaded = true;
        if (statusNode) statusNode.textContent = `CAD mesh loaded / ${meshes.length} parts`;
      } catch (error) {
        cadRobot.visible = false;
        proxyBody.visible = true;
        head.visible = true;
        current.cadLoaded = false;
        if (statusNode) statusNode.textContent = `CAD mesh unavailable, proxy active: ${error.message}`;
        console.error(error);
      }
    }

    function resize() {
      const width = Math.max(320, viewport.clientWidth);
      const height = Math.max(360, viewport.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }

    function sensorState(value) {
      const n = Number(value);
      if (!Number.isFinite(n) || n >= 999) return { level: 'unknown', color: 0x71808c, cm: 420, alive: false };
      if (n <= 60) return { level: 'bad', color: 0xff5d52, cm: Math.max(8, n), alive: true };
      if (n <= 120) return { level: 'warn', color: 0xffc857, cm: Math.max(8, n), alive: true };
      return { level: 'good', color: 0x39d98a, cm: Math.max(8, Math.min(420, n)), alive: true };
    }

    function sectorGeometry(centerDeg, widthDeg, radiusCm) {
      const segments = 28;
      const vertices = [0, 2.5, 0];
      const indices = [];
      const start = centerDeg - widthDeg;
      const end = centerDeg + widthDeg;
      for (let i = 0; i <= segments; i += 1) {
        const angle = (start + (end - start) * (i / segments)) * Math.PI / 180;
        vertices.push(Math.sin(angle) * radiusCm, 2.5, -Math.cos(angle) * radiusCm);
      }
      for (let i = 1; i <= segments; i += 1) {
        indices.push(0, i, i + 1);
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
      geometry.setIndex(indices);
      geometry.computeVertexNormals();
      return geometry;
    }

    function updateBeam(beam, rawValue) {
      const state = sensorState(rawValue);
      beam.mesh.geometry.dispose();
      beam.mesh.geometry = sectorGeometry(beam.angle, beam.width, state.cm);
      beam.mesh.material = materials[state.level] || materials.unknown;
      beam.marker.material.color.setHex(state.color);
      beam.marker.visible = state.alive;
      const angle = beam.angle * Math.PI / 180;
      beam.marker.position.x = Math.sin(angle) * state.cm;
      beam.marker.position.z = -Math.cos(angle) * state.cm;
      return state;
    }

    function updateEnvelope(dance) {
      const size = Number(dance.envelope_size_cm || 300);
      const half = Math.max(70, size / 2);
      const points = [
        new THREE.Vector3(-half, 0, -half),
        new THREE.Vector3(half, 0, -half),
        new THREE.Vector3(half, 0, half),
        new THREE.Vector3(-half, 0, half),
        new THREE.Vector3(-half, 0, -half),
      ];
      envelopeLine.geometry.dispose();
      envelopeLine.geometry = new THREE.BufferGeometry().setFromPoints(points);

      const x = Number(dance.estimated_x_cm || 0);
      const y = Number(dance.estimated_y_cm || 0);
      const px = Number(dance.predicted_x_cm || x);
      const py = Number(dance.predicted_y_cm || y);
      predictionLine.geometry.dispose();
      predictionLine.geometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(x, 0, -y),
        new THREE.Vector3(px, 0, -py),
      ]);
      predictionLine.material = String(dance.direction_safety || '').includes('unsafe') ? materials.lineBad : materials.lineGood;
    }

    function modeColor(mode) {
      if (mode === 'ERROR') return 0xff5d52;
      if (mode === 'DANCE') return 0x00b7c7;
      if (mode === 'WELCOME') return 0x39d98a;
      if (mode === 'MANUAL') return 0xffc857;
      if (mode === 'IDLE') return 0x52a8ff;
      return 0x8ea3b3;
    }

    function update(data, derived = {}) {
      const stm = data.stm32_runtime || {};
      const tel = stm.telemetry || {};
      const obstacles = stm.obstacles || {};
      const orientation = stm.imu_orientation || {};
      const mode = data.current_state || 'UNKNOWN';
      const yawDeg = Number.isFinite(Number(orientation.yaw))
        ? Number(orientation.yaw)
        : Number(tel.H || 0) * 180 / Math.PI;

      current.mode = mode;
      current.heading = yawDeg * Math.PI / 180;
      current.speed = Number(tel.SPD || 0);
      current.stateColor = modeColor(mode);
      current.sensorConfidence = Number(derived.sensorConfidence || 0);

      robot.rotation.y = -current.heading;
      robot.position.x = Number(tel.X || 0);
      robot.position.z = -Number(tel.Y || 0);

      const color = new THREE.Color(current.stateColor);
      materials.face.emissive.copy(color);
      materials.tablet.emissive.copy(color);
      rim.color.copy(color);

      updateBeam(beams[0], obstacles.FL);
      updateBeam(beams[1], obstacles.F);
      updateBeam(beams[2], obstacles.FR);
      updateEnvelope(data.dance || {});

      const confidenceBoost = Math.max(0.25, Math.min(1.0, current.sensorConfidence / 100));
      materials.face.emissiveIntensity = 0.35 + confidenceBoost * 0.65;
      mouth.scale.x = mode === 'IDLE' ? 1.25 : mode === 'ERROR' ? 0.55 : 1;

      if (statusNode) {
        const meshMode = current.cadLoaded ? 'CAD robot mesh' : 'proxy robot mesh';
        statusNode.textContent = `${mode} / ${derived.corridorLevel || 'corridor'} / ${meshMode} / ${current.sensorConfidence}% confidence`;
      }
    }

    function animate() {
      const elapsed = (performance.now() - startedAt) / 1000;
      const bob = current.mode === 'IDLE' ? Math.sin(elapsed * 1.65) * 2.4 : 0;
      head.rotation.y = Math.sin(elapsed * 0.55) * 0.08;
      head.position.y = 132 + bob;
      face.scale.y = 1 + Math.sin(elapsed * 2.4) * 0.018;
      for (const wheel of wheelMeshes) {
        wheel.rotation.x += current.speed * 0.0025;
      }
      for (const wheel of cadWheelMeshes) {
        wheel.rotation.x += current.speed * 0.0025;
      }
      const orbit = elapsed * 0.035;
      camera.position.x = Math.cos(orbit) * 430;
      camera.position.z = Math.sin(orbit) * 210 + 430;
      camera.lookAt(robot.position.x, 65, robot.position.z);
      renderer.render(scene, camera);
      requestAnimationFrame(animate);
    }

    const observer = new ResizeObserver(resize);
    observer.observe(viewport);
    window.addEventListener('resize', resize);
    resize();
    api.ready = true;
    api.update = update;
    if (statusNode) statusNode.textContent = '3D monitor ready';
    loadCadRobot();
    animate();
  } catch (error) {
    if (statusNode) statusNode.textContent = `3D unavailable: ${error.message}`;
    console.error(error);
  }
}
