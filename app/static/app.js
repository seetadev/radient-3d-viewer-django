import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { mergeGeometries, mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';

const $ = (sel) => document.querySelector(sel);
const container = $('#viewer-container');
const statusEl = $('#load-status');
const colorInput = $('#hex-color');
// Hosting apps may override these on #viewer-container (the Django port does); defaults suit Tornado.
const MODELS_URL = container.dataset.modelsUrl || '/models/';
const STATIC_URL = container.dataset.staticUrl || '/static/';

let scene, camera, renderer, pointLight;
let mesh = null;        // declared up front: the animation loop reads it before the first model loads
let loadToken = 0;      // ignore results of superseded loads (fast model switching)

const loader = new GLTFLoader();
const envMap = new THREE.CubeTextureLoader().load(
  ['px', 'nx', 'py', 'ny', 'pz', 'nz'].map((s) => `${STATIC_URL}cubemap/${s}.jpg`));
envMap.colorSpace = THREE.SRGBColorSpace;

const material = new THREE.MeshStandardMaterial({
  color: new THREE.Color(colorInput.value),
  metalness: 0.4,
  roughness: 0.05,
  envMap,
});

function viewerSize() {
  return [container.clientWidth, 0.8 * window.innerHeight];
}

function setLights() {
  scene.add(new THREE.AmbientLight(0x222222, Math.PI));
  const directional = new THREE.DirectionalLight(0xffffff, Math.PI);
  directional.position.set(1, 1, 1).normalize();
  scene.add(directional);
  pointLight = new THREE.PointLight(0xffffff, 2 * Math.PI, 800, 0);
  scene.add(pointLight);
  moveLight();
}

function loadScene() {
  const [w, h] = viewerSize();
  scene = new THREE.Scene();
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(w, h);
  renderer.setClearColor(0xdedede);
  camera = new THREE.PerspectiveCamera(40, w / h, 1, 2000);
  scene.add(camera);
  setLights();
  moveCamera();
  container.appendChild(renderer.domElement);
  window.addEventListener('resize', () => {
    const [nw, nh] = viewerSize();
    renderer.setSize(nw, nh);
    camera.aspect = nw / nh;
    camera.updateProjectionMatrix();
  });
}

function activeModelName() {
  return document.querySelector('.model-btn.active').textContent.trim();
}

function clearMesh() {
  if (mesh) {
    scene.remove(mesh);
    mesh.geometry.dispose();
    mesh = null;
  }
}

// The viewer shades every model with one material and smooth normals, so merge all
// primitives of the GLB into one geometry and recompute normals across shared vertices.
function toSingleGeometry(root) {
  const parts = [];
  root.traverse((o) => {
    if (o.isMesh) {
      const g = o.geometry.clone();
      g.deleteAttribute('normal');
      g.deleteAttribute('uv');
      parts.push(g);
    }
  });
  const merged = mergeVertices(mergeGeometries(parts, false));
  merged.computeVertexNormals();
  merged.computeBoundingBox();
  return merged;
}

function loadModel() {
  const name = activeModelName();
  const token = ++loadToken;
  statusEl.style.visibility = 'visible';
  statusEl.textContent = 'Loading your model, please wait...';
  container.dataset.loaded = 'false';
  loader.load(`${MODELS_URL}${name}.glb`, (gltf) => {
    if (token !== loadToken) return;
    statusEl.style.visibility = 'hidden';
    clearMesh();
    const geometry = toSingleGeometry(gltf.scene);
    mesh = new THREE.Mesh(geometry, material);
    scaleCenterMesh(mesh);
    scene.add(mesh);
    moveCamera();
    moveLight();
    container.dataset.model = name;
    container.dataset.loaded = 'true';
  }, undefined, (err) => {
    if (token !== loadToken) return;
    console.error(`Failed to load model ${name}`, err);
    statusEl.textContent = `Failed to load ${name}.`;
  });
}

function setCameraRanges(maxVal) {
  for (const id of ['camera-distance', 'camera-height']) $(`#${id}`).max = String(maxVal);
  $('#camera-distance').value = maxVal * 0.5;
  $('#camera-height').value = maxVal * 0.2;
}

function scaleCenterMesh(m) {
  const { min, max } = m.geometry.boundingBox;
  const [x, y, z] = [max.x - min.x, max.y - min.y, max.z - min.z];
  m.position.y = -y / 2;
  setCameraRanges(Math.max(x, y, z) * 3.5);
}

function moveCamera() {
  const distance = Number($('#camera-distance').value);
  const height = Number($('#camera-height').value);
  const radians = (Math.PI * 2 / 360) * Number($('#camera-degree').value);
  camera.position.set(distance * Math.cos(radians), height, distance * Math.sin(radians));
  camera.lookAt(scene.position);
}

function moveLight() {
  pointLight.position.set(
    Number($('#pointLight-x').value), Number($('#pointLight-y').value), Number($('#pointLight-z').value));
}

const MOVES = { UP: ['y', 1], DOWN: ['y', -1], LEFT: ['x', -1], RIGHT: ['x', 1], FRONT: ['z', 1], BACK: ['z', -1] };
let moveTimer = null;

function startMove(dir) {
  stopMove();
  const [axis, sign] = MOVES[dir];
  const step = () => { if (mesh) mesh.position[axis] += 0.01 * sign; };
  step();
  moveTimer = setInterval(step, 10);
}
function stopMove() { clearInterval(moveTimer); moveTimer = null; }

for (const btn of document.querySelectorAll('[data-move]')) {
  btn.addEventListener('pointerdown', () => startMove(btn.dataset.move));
}
document.addEventListener('pointerup', stopMove);
document.addEventListener('pointercancel', stopMove);

for (const btn of document.querySelectorAll('.model-btn')) {
  btn.addEventListener('click', () => {
    document.querySelector('.model-btn.active').classList.remove('active');
    btn.classList.add('active');
    loadModel();
  });
}

colorInput.addEventListener('input', () => material.color.set(colorInput.value));

loadScene();
loadModel();
renderer.setAnimationLoop(() => {
  if (mesh) {
    moveCamera();
    moveLight();
    renderer.render(scene, camera);
  }
});
