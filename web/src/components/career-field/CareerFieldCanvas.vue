<template>
  <div
    ref="root"
    class="career-field"
    :class="[`career-field--${variant}`, `career-field--${state}`]"
    role="img"
    aria-label="启航生涯领域控制台三维示意图"
  >
    <canvas ref="canvas" class="career-field__canvas" aria-hidden="true" />

    <div class="career-field__fallback" aria-hidden="true">
      <span class="career-field__fallback-halo" />
      <span class="career-field__fallback-ring career-field__fallback-ring--one" />
      <span class="career-field__fallback-ring career-field__fallback-ring--two" />
      <span class="career-field__fallback-core" />
    </div>

    <div class="career-field__chrome">
      <div class="career-field__topline">
        <span class="career-field__brand">
          <i />
          CAREER FIELD
        </span>
        <span class="career-field__mode">MODEL / LIVE</span>
      </div>

      <span class="career-field__axis career-field__axis--x" aria-hidden="true" />
      <span class="career-field__axis career-field__axis--y" aria-hidden="true" />

      <span
        v-for="node in nodeLabels"
        :key="node.key"
        class="career-field__node"
        :class="`career-field__node--${node.key}`"
      >
        <i :style="{ background: node.cssColor }" />
        <span>{{ node.label }}</span>
        <small>{{ node.code }}</small>
      </span>

      <div class="career-field__footer">
        <span>ACADEMIC → ABILITY → DIRECTION → CAREER</span>
        <span>{{ reducedMotion ? 'STATIC FRAME' : 'FIELD ACTIVE' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
// 职责：绘制启航生涯领域控制台的轻量 Three.js 视觉，并提供无 WebGL 回退。
// 输入：尺寸、展示密度与暂停状态；不接收或生成任何业务数值。
// 输出：装饰性三维场景；全部中文标签由模板静态提供，可被无障碍读取。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  variant: {
    type: String,
    default: 'full'
  },
  paused: {
    type: Boolean,
    default: false
  },
  quality: {
    type: String,
    default: 'auto'
  },
  interactive: {
    type: Boolean,
    default: true
  }
})

const NODE_LAYOUT = [
  {
    key: 'study',
    label: '学业轨迹',
    code: 'STUDY',
    color: 0x0f9d8a,
    cssColor: '#0f9d8a',
    position: [1.72, 0.56, 0.1]
  },
  {
    key: 'ability',
    label: '能力结构',
    code: 'ABILITY',
    color: 0x46c9bf,
    cssColor: '#46c9bf',
    position: [-1.45, 0.92, 0.58]
  },
  {
    key: 'direction',
    label: '职业方向',
    code: 'DIRECTION',
    color: 0xff5a3c,
    cssColor: '#5b5bd6',
    position: [-1.28, -0.98, 0.3]
  },
  {
    key: 'career',
    label: '岗位目标',
    code: 'CAREER',
    color: 0x91aaa9,
    cssColor: '#91aaa9',
    position: [1.36, -1.06, -0.24]
  }
]

const nodeLabels = NODE_LAYOUT.map(({ key, label, code, cssColor }) => ({
  key,
  label,
  code,
  cssColor
}))

const root = ref(null)
const canvas = ref(null)
const state = ref('loading')
const reducedMotion = ref(false)
const compact = computed(() => props.variant === 'compact')

let destroyScene = null
let resizeObserver = null
let intersectionObserver = null
let motionQuery = null
let coarsePointerQuery = null
let onPointerMove = null
let onPointerLeave = null
let onVisibilityChange = null
let onMotionChange = null

function prefersReducedMotion() {
  return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
}

async function startScene() {
  if (!canvas.value || !root.value) return

  try {
    const THREE = await import('three')
    if (!canvas.value || !root.value) return

    reducedMotion.value = prefersReducedMotion()
    motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    coarsePointerQuery = window.matchMedia('(pointer: coarse)')

    const lowQuality =
      props.quality === 'low' ||
      (props.quality === 'auto' && coarsePointerQuery.matches)
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100)
    camera.position.set(0, 0.3, 8.2)

    const renderer = new THREE.WebGLRenderer({
      canvas: canvas.value,
      alpha: true,
      antialias: !lowQuality,
      powerPreference: 'high-performance'
    })
    renderer.setClearColor(0x000000, 0)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.NeutralToneMapping
    renderer.toneMappingExposure = 1.03
    renderer.setPixelRatio(
      Math.min(window.devicePixelRatio || 1, lowQuality ? 1.25 : 1.75)
    )

    const world = new THREE.Group()
    world.rotation.x = -0.08
    scene.add(world)

    const coreGroup = new THREE.Group()
    world.add(coreGroup)

    const materials = {
      core: new THREE.MeshStandardMaterial({
        color: 0x0e3a3d,
        metalness: 0.72,
        roughness: 0.24
      }),
      steel: new THREE.MeshStandardMaterial({
        color: 0x9db3b1,
        metalness: 0.8,
        roughness: 0.3
      }),
      ceramic: new THREE.MeshStandardMaterial({
        color: 0xf8fcfb,
        metalness: 0.05,
        roughness: 0.46
      }),
      teal: new THREE.MeshStandardMaterial({
        color: 0x0f9d8a,
        metalness: 0.2,
        roughness: 0.28,
        emissive: 0x0f9d8a,
        emissiveIntensity: 0.1
      }),
      aqua: new THREE.MeshStandardMaterial({
        color: 0x46c9bf,
        metalness: 0.18,
        roughness: 0.3,
        emissive: 0x46c9bf,
        emissiveIntensity: 0.08
      }),
      coral: new THREE.MeshStandardMaterial({
        color: 0xff5a3c,
        metalness: 0.12,
        roughness: 0.32,
        emissive: 0xff5a3c,
        emissiveIntensity: 0.08
      }),
      line: new THREE.LineBasicMaterial({
        color: 0x8eb9b6,
        transparent: true,
        opacity: 0.46
      }),
      faintLine: new THREE.LineBasicMaterial({
        color: 0xa9ccca,
        transparent: true,
        opacity: 0.34
      })
    }

    const core = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.56, lowQuality ? 1 : 2),
      materials.core
    )
    coreGroup.add(core)

    const coreShell = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.66, lowQuality ? 1 : 2),
      new THREE.MeshBasicMaterial({
        color: 0x46c9bf,
        wireframe: true,
        transparent: true,
        opacity: 0.3
      })
    )
    coreGroup.add(coreShell)

    const rotatingRings = []
    const ringSpecs = [
      [1.02, 0.018, 0.32, 0.28],
      [1.18, 0.012, -0.62, 0.44],
      [1.34, 0.009, 1.06, -0.16]
    ]
    for (const [radius, tube, x, y] of ringSpecs) {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(radius, tube, 8, lowQuality ? 64 : 120),
        materials.ceramic
      )
      ring.rotation.set(x, y, 0)
      coreGroup.add(ring)
      rotatingRings.push(ring)
    }

    const cueRing = new THREE.Mesh(
      new THREE.TorusGeometry(0.86, 0.026, 10, 96),
      materials.coral
    )
    cueRing.rotation.x = Math.PI / 2.8
    coreGroup.add(cueRing)

    const nodeGroups = []
    for (const nodeDef of NODE_LAYOUT) {
      const node = new THREE.Group()
      node.position.set(...nodeDef.position)

      const orb = new THREE.Mesh(
        new THREE.IcosahedronGeometry(0.15, 1),
        new THREE.MeshStandardMaterial({
          color: nodeDef.color,
          metalness: 0.22,
          roughness: 0.25,
          emissive: nodeDef.color,
          emissiveIntensity: 0.08
        })
      )
      node.add(orb)

      const halo = new THREE.Mesh(
        new THREE.TorusGeometry(0.28, 0.008, 6, 52),
        new THREE.MeshBasicMaterial({
          color: nodeDef.color,
          transparent: true,
          opacity: 0.56
        })
      )
      halo.rotation.x = Math.PI / 2.7
      halo.rotation.y = 0.38
      node.add(halo)

      const socket = new THREE.Mesh(
        new THREE.CylinderGeometry(0.055, 0.075, 0.16, 12),
        materials.steel
      )
      socket.position.y = -0.26
      node.add(socket)

      world.add(node)
      nodeGroups.push({ node, halo, orb, baseY: nodeDef.position[1] })

      const start = new THREE.Vector3(0, 0, 0)
      const end = new THREE.Vector3(...nodeDef.position)
      const control = end
        .clone()
        .multiplyScalar(0.56)
        .add(new THREE.Vector3(0, Math.sign(end.y || 1) * 0.24, 0.2))
      const curve = new THREE.QuadraticBezierCurve3(start, control, end)
      const connector = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(curve.getPoints(36)),
        new THREE.LineBasicMaterial({
          color: nodeDef.color,
          transparent: true,
          opacity: 0.3
        })
      )
      world.add(connector)
    }

    const stageGroup = new THREE.Group()
    stageGroup.rotation.x = Math.PI / 2.42
    world.add(stageGroup)

    for (const radius of [2.1, 2.46, 2.82]) {
      const points = []
      const segments = lowQuality ? 72 : 128
      for (let index = 0; index <= segments; index += 1) {
        const angle = (index / segments) * Math.PI * 2
        points.push(
          new THREE.Vector3(
            Math.cos(angle) * radius,
            Math.sin(angle) * radius,
            0
          )
        )
      }
      stageGroup.add(
        new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(points),
          radius === 2.46 ? materials.line : materials.faintLine
        )
      )
    }

    const tickPositions = []
    const tickCount = lowQuality ? 48 : 72
    for (let index = 0; index < tickCount; index += 1) {
      const angle = (index / tickCount) * Math.PI * 2
      const inner = index % 6 === 0 ? 2.08 : 2.16
      const outer = index % 6 === 0 ? 2.26 : 2.2
      tickPositions.push(
        Math.cos(angle) * inner,
        Math.sin(angle) * inner,
        0,
        Math.cos(angle) * outer,
        Math.sin(angle) * outer,
        0
      )
    }
    const tickGeometry = new THREE.BufferGeometry()
    tickGeometry.setAttribute(
      'position',
      new THREE.Float32BufferAttribute(tickPositions, 3)
    )
    stageGroup.add(new THREE.LineSegments(tickGeometry, materials.line))

    const atmosphere = new THREE.Group()
    world.add(atmosphere)
    const particleCount = lowQuality ? 42 : 88
    const particlePositions = []
    let seed = 4107
    const random = () => {
      seed = (seed * 1664525 + 1013904223) >>> 0
      return seed / 0xffffffff
    }
    for (let index = 0; index < particleCount; index += 1) {
      const radius = 2.2 + random() * 1.7
      const theta = random() * Math.PI * 2
      const phi = Math.acos(2 * random() - 1)
      particlePositions.push(
        radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi) * 0.7,
        radius * Math.sin(phi) * Math.sin(theta)
      )
    }
    const particleGeometry = new THREE.BufferGeometry()
    particleGeometry.setAttribute(
      'position',
      new THREE.Float32BufferAttribute(particlePositions, 3)
    )
    atmosphere.add(
      new THREE.Points(
        particleGeometry,
        new THREE.PointsMaterial({
          color: 0x46c9bf,
          size: 0.026,
          sizeAttenuation: true,
          transparent: true,
          opacity: 0.48
        })
      )
    )

    scene.add(new THREE.HemisphereLight(0xf7fffe, 0x7da7a4, 2.25))
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.4)
    keyLight.position.set(4.5, 7, 5.5)
    scene.add(keyLight)
    const coralLight = new THREE.PointLight(0xff5a3c, 7, 8, 2)
    coralLight.position.set(-2.8, -1.2, 2.2)
    scene.add(coralLight)

    const pointerTarget = { x: 0, y: 0 }
    const pointerCurrent = { x: 0, y: 0 }
    let elapsed = 0
    let previousTime = performance.now()
    let frameId = 0
    let visible = true
    let renderedOnce = false
    let destroyed = false

    const render = () => {
      renderer.render(scene, camera)
      renderedOnce = true
    }

    const resize = () => {
      if (!root.value || destroyed) return
      const rect = root.value.getBoundingClientRect()
      const width = Math.max(1, Math.round(rect.width))
      const height = Math.max(1, Math.round(rect.height))
      renderer.setSize(width, height, false)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      render()
    }

    const frame = (time) => {
      if (destroyed) return
      frameId = window.requestAnimationFrame(frame)
      if (!visible || document.hidden || props.paused) return
      if (reducedMotion.value) {
        if (!renderedOnce) render()
        return
      }

      const delta = Math.min((time - previousTime) / 1000, 0.05)
      previousTime = time
      elapsed += delta

      pointerCurrent.x += (pointerTarget.x - pointerCurrent.x) * 0.035
      pointerCurrent.y += (pointerTarget.y - pointerCurrent.y) * 0.035

      world.rotation.y = elapsed * 0.075 + pointerCurrent.x * 0.16
      world.rotation.x = -0.08 + Math.sin(elapsed * 0.32) * 0.025 + pointerCurrent.y * 0.08
      coreGroup.rotation.y = elapsed * 0.13
      coreShell.rotation.y = -elapsed * 0.18
      coreShell.rotation.z = elapsed * 0.08
      cueRing.rotation.z = elapsed * 0.22
      stageGroup.rotation.z = elapsed * 0.028
      atmosphere.rotation.y = -elapsed * 0.018

      rotatingRings.forEach((ring, index) => {
        ring.rotation.z += delta * (0.09 + index * 0.025)
      })
      nodeGroups.forEach((entry, index) => {
        entry.node.position.y =
          entry.baseY + Math.sin(elapsed * 0.62 + index * 1.4) * 0.045
        entry.halo.rotation.z += delta * (0.1 + index * 0.02)
      })

      render()
    }

    onPointerMove = (event) => {
      if (!props.interactive || lowQuality) return
      const rect = root.value.getBoundingClientRect()
      pointerTarget.x = ((event.clientX - rect.left) / rect.width - 0.5) * 2
      pointerTarget.y = ((event.clientY - rect.top) / rect.height - 0.5) * 2
    }
    onPointerLeave = () => {
      pointerTarget.x = 0
      pointerTarget.y = 0
    }
    onVisibilityChange = () => {
      renderedOnce = false
    }
    onMotionChange = (event) => {
      reducedMotion.value = event.matches
      renderedOnce = false
    }

    root.value.addEventListener('pointermove', onPointerMove, { passive: true })
    root.value.addEventListener('pointerleave', onPointerLeave, { passive: true })
    motionQuery.addEventListener?.('change', onMotionChange)
    document.addEventListener('visibilitychange', onVisibilityChange)

    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(root.value)

    intersectionObserver = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting
        if (visible) renderedOnce = false
      },
      { threshold: 0.01 }
    )
    intersectionObserver.observe(root.value)

    resize()
    state.value = 'ready'
    frameId = window.requestAnimationFrame(frame)

    destroyScene = () => {
      destroyed = true
      window.cancelAnimationFrame(frameId)
      resizeObserver?.disconnect()
      intersectionObserver?.disconnect()
      root.value?.removeEventListener('pointermove', onPointerMove)
      root.value?.removeEventListener('pointerleave', onPointerLeave)
      motionQuery?.removeEventListener?.('change', onMotionChange)
      document.removeEventListener('visibilitychange', onVisibilityChange)

      const geometries = new Set()
      const sceneMaterials = new Set()
      scene.traverse((object) => {
        if (object.geometry) geometries.add(object.geometry)
        if (Array.isArray(object.material)) {
          object.material.forEach((material) => sceneMaterials.add(material))
        } else if (object.material) {
          sceneMaterials.add(object.material)
        }
      })
      geometries.forEach((geometry) => geometry.dispose())
      sceneMaterials.forEach((material) => material.dispose())
      renderer.dispose()
    }
  } catch {
    state.value = 'fallback'
  }
}

onMounted(startScene)

onBeforeUnmount(() => {
  if (destroyScene) destroyScene()
  else {
    resizeObserver?.disconnect()
    intersectionObserver?.disconnect()
  }
})
</script>

<style scoped>
.career-field {
  --field-ink: #16181d;
  --field-mid: #5f6672;
  --field-faint: #9aa1ad;
  --field-line: #e4e7ee;
  --field-coral: #5b5bd6;
  position: relative;
  width: 100%;
  min-height: 360px;
  overflow: hidden;
  isolation: isolate;
  border-radius: inherit;
  background:
    radial-gradient(circle at 50% 45%, rgba(250, 254, 253, 0.94), transparent 34%),
    radial-gradient(circle at 50% 50%, #effbfa 0%, #eef0f5 100%);
  color: var(--field-ink);
  touch-action: pan-y;
}

.career-field::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  background-image:
    linear-gradient(rgba(14, 58, 61, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(14, 58, 61, 0.045) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: radial-gradient(circle at 50% 50%, #000 0%, transparent 76%);
  pointer-events: none;
}

.career-field::after {
  content: '';
  position: absolute;
  inset: 14px;
  z-index: 2;
  border: 1px solid rgba(93, 130, 132, 0.15);
  border-radius: calc(8px - 2px);
  pointer-events: none;
}

.career-field--full {
  min-height: 100%;
}

.career-field--compact {
  min-height: 280px;
}

.career-field__canvas {
  position: absolute;
  inset: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  display: block;
  cursor: crosshair;
}

.career-field__fallback {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: grid;
  place-items: center;
  transition: opacity 420ms ease;
}

.career-field--ready .career-field__fallback {
  opacity: 0;
  pointer-events: none;
}

.career-field__fallback-halo {
  position: absolute;
  width: min(40vw, 340px);
  aspect-ratio: 1;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(70, 201, 191, 0.2), transparent 66%);
  filter: blur(8px);
}

.career-field__fallback-ring {
  position: absolute;
  border: 1px solid rgba(14, 58, 61, 0.24);
  border-radius: 50%;
  transform: rotateX(62deg) rotateZ(-12deg);
  animation: career-field-spin 18s linear infinite;
}

.career-field__fallback-ring--one {
  width: min(46vw, 390px);
  height: min(26vw, 220px);
}

.career-field__fallback-ring--two {
  width: min(34vw, 290px);
  height: min(19vw, 160px);
  border-color: rgba(91, 91, 214, 0.35);
  animation-direction: reverse;
  animation-duration: 13s;
}

.career-field__fallback-core {
  width: 74px;
  height: 74px;
  border: 1px solid rgba(255, 255, 255, 0.92);
  border-radius: 26px;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.8), rgba(70, 201, 191, 0.2)),
    #16181d;
  box-shadow:
    inset 0 1px 1px rgba(255, 255, 255, 0.28),
    0 18px 50px rgba(14, 58, 61, 0.2);
  transform: rotate(12deg);
}

.career-field__chrome {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
}

.career-field__topline,
.career-field__footer {
  position: absolute;
  left: 28px;
  right: 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  color: var(--field-mid);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.14em;
}

.career-field__topline {
  top: 24px;
}

.career-field__footer {
  bottom: 22px;
}

.career-field__brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--field-ink);
}

.career-field__brand i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--field-coral);
  box-shadow: 0 0 0 5px rgba(91, 91, 214, 0.1);
}

.career-field__mode {
  padding-left: 12px;
  border-left: 1px solid var(--field-line);
}

.career-field__axis {
  position: absolute;
  background: linear-gradient(90deg, transparent, rgba(14, 58, 61, 0.22), transparent);
}

.career-field__axis--x {
  left: 8%;
  right: 8%;
  top: 50%;
  height: 1px;
}

.career-field__axis--y {
  top: 8%;
  bottom: 8%;
  left: 50%;
  width: 1px;
  background: linear-gradient(180deg, transparent, rgba(14, 58, 61, 0.18), transparent);
}

.career-field__node {
  position: absolute;
  display: grid;
  grid-template-columns: 7px auto;
  grid-template-rows: auto auto;
  column-gap: 7px;
  align-items: center;
  padding: 7px 9px;
  border: 1px solid rgba(228, 231, 238, 0.88);
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.62);
  box-shadow: 0 6px 24px rgba(16, 24, 40, 0.06);
  backdrop-filter: blur(8px);
  color: var(--field-ink);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
}

.career-field__node i {
  grid-row: span 2;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.career-field__node small {
  color: var(--field-faint);
  font-size: 8px;
  letter-spacing: 0.13em;
}

.career-field__node--study {
  right: 24%;
  top: 28%;
}

.career-field__node--ability {
  left: 26%;
  top: 22%;
}

.career-field__node--direction {
  left: 28%;
  bottom: 24%;
}

.career-field__node--career {
  right: 24%;
  bottom: 20%;
}

.career-field--compact .career-field__node {
  padding: 5px 7px;
  font-size: 9px;
}

.career-field--compact .career-field__node small {
  display: none;
}

@keyframes career-field-spin {
  to {
    transform: rotateX(62deg) rotateZ(348deg);
  }
}

@media (max-width: 640px) {
  .career-field {
    min-height: 240px;
  }

  .career-field__topline,
  .career-field__footer {
    left: 18px;
    right: 18px;
  }

  .career-field__topline {
    top: 18px;
  }

  .career-field__footer {
    bottom: 16px;
  }

  .career-field__footer span:first-child {
    display: none;
  }

  .career-field__node small {
    display: none;
  }

  .career-field__node--study {
    right: 7%;
    top: 27%;
  }

  .career-field__node--ability {
    left: 7%;
    top: 24%;
  }

  .career-field__node--direction {
    left: 7%;
    bottom: 27%;
  }

  .career-field__node--career {
    right: 7%;
    bottom: 24%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .career-field__fallback-ring {
    animation: none;
  }
}
</style>
