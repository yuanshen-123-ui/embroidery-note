<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import HanziWriter from 'hanzi-writer'
import Icon from './Icon.vue'

/* ---------------- 常量 ---------------- */
const CELL = 76           // 单字格子
const PAD = 4
const SPEED = 1.1         // 与 hanzi-writer strokeAnimationSpeed 一致，针画同步
const MAX_CHARS = 72
const PALETTE = ['#c0504d', '#4f8a54', '#3f5f9e', '#8455a8', '#7ea13f', '#d16a8a']
const BLUE = '#3f5f9e'
const IS_CJK = (ch) => /[\u3400-\u9fff\uf900-\ufaff]/.test(ch)

const LOCAL_NOTES = [
  { id: 1, title: '宝贝', text: '这个世界破破烂烂，\n只有你治愈了我，\n我爱你，宝贝' },
  { id: 2, title: '晚安', text: '今天也是想你的一天，\n晚安，做个好梦。' },
  { id: 3, title: '打气', text: '慢慢来，别着急，\n你已经在很努力地发光了。' },
  { id: 4, title: '生日', text: '祝你生日快乐，\n愿你被这个世界温柔以待。' },
  { id: 5, title: '感谢', text: '谢谢你出现在我的生命里，\n像春天路过荒原。' },
]

/* ---------------- 状态 ---------------- */
const input = ref('')
const stitched = ref([])        // { id, ch, color, type: 'cjk'|'plain'|'nl' }
const notes = ref(LOCAL_NOTES)
const apiOk = ref(false)        // 后端可达时才显示"生成图片"
const status = ref('')
const threadColor = ref(PALETTE[0])
const needleVisible = ref(false)

const cardEl = ref(null)
const needleEl = ref(null)

let prevLen = 0
let uid = 0
let colorIdx = 0
let playGen = 0
let chain = Promise.resolve()
const cellEls = new Map()
const dataCache = new Map()
const needlePos = { x: 0, y: 0 }

const setCellRef = (id) => (el) => {
  if (el) cellEls.set(id, el)
  else cellEls.delete(id)
}

/* ---------------- 笔画数据：同源优先，CDN 多级兜底 ---------------- */
const DATA_SOURCES = [
  'hanzi-data/',                                              // 本地后端 / 自托管 / Pages 同源
  'https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0/',
  'https://fastly.jsdelivr.net/npm/hanzi-writer-data@2.0/',
  'https://unpkg.com/hanzi-writer-data@2.0/',
]
async function fetchCharData(ch) {
  if (dataCache.has(ch)) return dataCache.get(ch)
  const name = encodeURIComponent(ch) + '.json'
  let lastErr
  for (const base of DATA_SOURCES) {
    try {
      const res = await fetch(base + name, { signal: AbortSignal.timeout(4000) })
      if (!res.ok) throw new Error(String(res.status))
      const data = await res.json()
      if (!data.strokes || !data.medians) throw new Error('bad data')
      dataCache.set(ch, data)
      return data
    } catch (e) {
      lastErr = e
    }
  }
  throw lastErr
}

/* ---------------- 针驱动：直接写 transform，绕过响应式开销 ---------------- */
function setNeedle(x, y) {
  needlePos.x = x
  needlePos.y = y
  if (needleEl.value) {
    needleEl.value.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`
  }
}

/* 沿等弧长采样点按进度取点（rAF + 线性插值，与 hanzi-writer 同步）
   注意：rAF 帧时间戳可能早于 t0（vsync 对齐），必须把进度钳制在 [0,1]，
   否则负索引会让整个播放队列崩溃 —— 这正是"针不动/画不出"的元凶 */
function animateAlong(pts, ms, gen) {
  return new Promise((resolve) => {
    const t0 = performance.now()
    const safeMs = Number.isFinite(ms) && ms > 0 ? ms : 400
    const step = (now) => {
      if (gen !== playGen) return resolve()
      const p = Math.max(0, Math.min(1, (now - t0) / safeMs))
      const f = p * (pts.length - 1)
      const i = Math.max(0, Math.min(Math.floor(f), pts.length - 2))
      const a = pts[i]
      const b = pts[i + 1] || a
      if (!a) return resolve()
      setNeedle(a[0] + (b[0] - a[0]) * ((f - i) || 0), a[1] + (b[1] - a[1]) * ((f - i) || 0))
      if (p < 1) requestAnimationFrame(step)
      else resolve()
    }
    requestAnimationFrame(step)
  })
}
function glide(target, ms, gen) {
  return animateAlong([[needlePos.x, needlePos.y], [target.x, target.y]], ms, gen)
}

/* ---------------- 坐标转换工具 ---------------- */
/* 中线按弧长均匀重采样（针走线迹中心线） */
function resampleByArc(median, n = 72) {
  const dist = [0]
  for (let i = 1; i < median.length; i++) {
    dist.push(dist[i - 1] + Math.hypot(median[i][0] - median[i - 1][0], median[i][1] - median[i - 1][1]))
  }
  const total = dist[dist.length - 1] || 1
  const out = []
  let seg = 1
  for (let k = 0; k <= n; k++) {
    const target = (total * k) / n
    while (seg < dist.length - 1 && dist[seg] < target) seg++
    const t = (target - dist[seg - 1]) / (dist[seg] - dist[seg - 1] || 1)
    out.push([
      median[seg - 1][0] + (median[seg][0] - median[seg - 1][0]) * t,
      median[seg - 1][1] + (median[seg][1] - median[seg - 1][1]) * t,
    ])
  }
  return out
}
/* 用 DOM 精确测量笔画 path 长度，套 hanzi-writer 时长公式 (len+600)/(3*speed) */
function domPathLength(d) {
  try {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    p.setAttribute('d', d)
    const len = p.getTotalLength()
    return Number.isFinite(len) ? len : 0
  } catch {
    return 0
  }
}

/* ---------------- 逐字绣制 ---------------- */
async function playItem(item, gen) {
  if (item.type === 'nl') return
  await nextTick()
  const host = cellEls.get(item.id)
  const card = cardEl.value
  if (!host || !card || gen !== playGen) return

  const cardRect = card.getBoundingClientRect()
  const hostRect = host.getBoundingClientRect()
  const ox = hostRect.left - cardRect.left
  const oy = hostRect.top - cardRect.top

  /* 非汉字：针跳到格子中央，直接以彩色文字呈现 */
  if (item.type !== 'cjk') {
    threadColor.value = item.color
    needleVisible.value = true
    await glide({ x: ox + CELL / 2, y: oy + CELL / 2 }, 240, gen)
    return
  }

  /* loadCharacterData：拿每一笔的 strokes(path) 与 medians(中线) */
  let data
  try {
    data = await fetchCharData(item.ch)
  } catch {
    item.type = 'plain' // 数据不可得（如离线）：回退彩色文字
    threadColor.value = item.color
    needleVisible.value = true
    await glide({ x: ox + CELL / 2, y: oy + CELL / 2 }, 240, gen)
    return
  }
  if (gen !== playGen) return

  /* getScalingTransform：transform = translate(x, H−y) scale(s, −s)
     ⇒ screen = (ox + x + s·px, oy + (H−y) − s·py)，数据坐标 x∈[0,1024]、y∈[−124,900]（y 朝上） */
  const st = HanziWriter.getScalingTransform(CELL, CELL, PAD)
  const ty = CELL - st.y
  const toScreen = (p) => [ox + st.x + st.scale * p[0], oy + ty - st.scale * p[1]]

  const strokeScreens = data.medians.map((m) => resampleByArc(m).map(toScreen))
  const durations = data.strokes.map((d) => (domPathLength(d) + 600) / (3 * SPEED))

  const writer = HanziWriter.create(host, item.ch, {
    width: CELL,
    height: CELL,
    padding: PAD,
    strokeColor: item.color,
    radicalColor: null,
    strokeAnimationSpeed: SPEED,
    delayBetweenStrokes: 150,
    showOutline: true,
    outlineColor: '#e9ddc8',
    showCharacter: false,
    charDataLoader: (c, done) => done(data), // 复用已取到的数据
  })

  threadColor.value = item.color
  needleVisible.value = true

  /* 上一字绣完 → 针滑到本字第一笔起点 */
  await glide({ x: strokeScreens[0][0][0], y: strokeScreens[0][0][1] }, 340, gen)

  for (let i = 0; i < strokeScreens.length; i++) {
    if (gen !== playGen) return
    const pts = strokeScreens[i]
    if (!pts || !pts.length) continue
    status.value = `「${item.ch}」第 ${i + 1}/${strokeScreens.length} 笔`
    setNeedle(pts[0][0], pts[0][1])
    /* 兜底：单笔动画即使失败/卡死也不拖垮整个队列 */
    const strokePromise = new Promise((res) => {
      try {
        writer.animateStroke(i, { onComplete: res })
      } catch {
        res()
      }
    })
    strokePromise.catch(() => {})
    const needleDone = animateAlong(pts, durations[i], gen)
    /* animateStroke(i) 逐笔播放，onComplete 后播下一笔 */
    await Promise.race([
      strokePromise,
      new Promise((res) => setTimeout(res, (durations[i] || 600) * 2 + 2500)),
    ])
    await needleDone
    setNeedle(pts[pts.length - 1][0], pts[pts.length - 1][1])
  }
  status.value = `「${item.ch}」绣好了`
}

/* ---------------- 输入 / 文案 ---------------- */
function enqueueText(str) {
  for (const ch of str) {
    if (stitched.value.length >= MAX_CHARS) {
      status.value = `最多绣 ${MAX_CHARS} 个字哦`
      break
    }
    const item = ch === '\n'
      ? { id: ++uid, ch, type: 'nl', color: '' }
      : { id: ++uid, ch, color: PALETTE[colorIdx++ % PALETTE.length], type: IS_CJK(ch) ? 'cjk' : 'plain' }
    stitched.value.push(item)
    if (item.type !== 'nl') {
      const gen = playGen
      chain = chain.then(() => playItem(item, gen)).catch(() => {})
    }
  }
}

function onInput() {
  if (composing.value) return
  const v = input.value
  if (v.length > prevLen) enqueueText(v.slice(prevLen))
  prevLen = v.length
}
const composing = ref(false)

function clearAll() {
  playGen++
  chain = Promise.resolve()
  stitched.value = []
  input.value = ''
  prevLen = 0
  needleVisible.value = false
  status.value = '已清空，重新开始吧'
}

function replay() {
  const seq = stitched.value.map((t) => t.ch).join('')
  playGen++
  chain = Promise.resolve()
  stitched.value = []
  needleVisible.value = false
  enqueueText(seq)
}

async function randomNote() {
  const pool = notes.value.length ? notes.value : LOCAL_NOTES
  const note = pool[Math.floor(Math.random() * pool.length)]
  playGen++
  chain = Promise.resolve()
  stitched.value = []
  input.value = ''
  prevLen = 0
  needleVisible.value = false
  status.value = `换一条文案：「${note.title}」，开绣…`
  enqueueText(note.text)
}

function currentText() {
  return stitched.value.map((t) => t.ch).join('')
}

async function copyText() {
  try {
    await navigator.clipboard.writeText(currentText())
    status.value = '文字已复制'
  } catch {
    status.value = '复制失败'
  }
}

async function generateImage() {
  try {
    const res = await fetch('/api/render?download=1', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: currentText() }),
    })
    if (!res.ok) throw new Error('render failed')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'embroidery-note.png'
    a.click()
    URL.revokeObjectURL(url)
    status.value = '图片已生成并开始下载'
  } catch {
    status.value = '生成失败：需要本地后端 (python backend/main.py)'
  }
}

onMounted(async () => {
  enqueueText(LOCAL_NOTES[0].text) // 开场自动绣默认文案
  /* GitHub Pages 等纯静态环境没有后端，直接走内置文案，不发必失败的探测请求 */
  const isStaticHost = /\.github\.io$|\.gitee\.io$/.test(location.hostname)
  if (isStaticHost) {
    apiOk.value = false
    return
  }
  try {
    const res = await fetch('/api/notes', { signal: AbortSignal.timeout(2500) })
    if (res.ok) {
      const data = await res.json()
      if (data.notes?.length) notes.value = data.notes
      apiOk.value = true
    }
  } catch {
    apiOk.value = false
  }
})

onBeforeUnmount(() => {
  playGen++
})

/* ---------------- 卡片装饰（波浪边框 / 圆点 / 花藤） ---------------- */
function wavyEdge(x1, y1, x2, y2, waves, amp) {
  let d = ''
  const len = Math.hypot(x2 - x1, y2 - y1)
  const nx = (-(y2 - y1) / len) * amp
  const ny = ((x2 - x1) / len) * amp
  for (let i = 0; i < waves; i++) {
    const t0 = i / waves
    const t1 = (i + 1) / waves
    const tm = (t0 + t1) / 2
    d += ` Q ${(x1 + (x2 - x1) * tm + nx).toFixed(1)} ${(y1 + (y2 - y1) * tm + ny).toFixed(1)} ${(x1 + (x2 - x1) * t1).toFixed(1)} ${(y1 + (y2 - y1) * t1).toFixed(1)}`
  }
  return d
}
function wavyRect(x, y, w, h, amp) {
  const n = 26
  return (
    `M ${x} ${y}` +
    wavyEdge(x, y, x + w, y, n, amp) +
    wavyEdge(x + w, y, x + w, y + h, n, amp) +
    wavyEdge(x + w, y + h, x, y + h, n, amp) +
    wavyEdge(x, y + h, x, y, n, amp) +
    ' Z'
  )
}
const borderPath = wavyRect(22, 22, 676, 690, 6)
const DOT_RECT = { x: 48, y: 48, w: 624, h: 638 }

const FLOWERS = [
  { x: 118, y: 52, r: 6 },
  { x: 168, y: 42, r: 5 },
  { x: 292, y: 42, r: 5 },
  { x: 342, y: 52, r: 6 },
]
function petals(f) {
  const pts = []
  for (let k = 0; k < 5; k++) {
    const a = ((72 * k - 90) * Math.PI) / 180
    pts.push({ cx: f.x + f.r * Math.cos(a), cy: f.y + f.r * Math.sin(a), r: f.r * 0.62 })
  }
  return pts
}
</script>

<template>
  <div class="page">
    <!-- 便签卡片 = 绣布 -->
    <div ref="cardEl" class="card">
      <svg class="border-svg" viewBox="0 0 720 734" preserveAspectRatio="none" aria-hidden="true">
        <path :d="borderPath" fill="none" :stroke="BLUE" stroke-width="3.4" />
        <rect
          :x="DOT_RECT.x" :y="DOT_RECT.y" :width="DOT_RECT.w" :height="DOT_RECT.h"
          fill="none" :stroke="BLUE" stroke-width="7"
          stroke-dasharray="0.1 27" stroke-linecap="round"
        />
      </svg>

      <!-- 顶部花藤 + 蝴蝶结 -->
      <svg class="ornament ornament-top" viewBox="0 0 460 80" aria-hidden="true">
        <g :stroke="BLUE" stroke-width="2.6" fill="none" stroke-linecap="round">
          <path d="M60,52 C40,62 22,54 26,41 C29,32 40,33 40,42 C40,49 32,51 28,47" />
          <path d="M60,52 C100,66 150,40 196,44" />
          <path d="M400,52 C420,62 438,54 434,41 C431,32 420,33 420,42 C420,49 428,51 432,47" />
          <path d="M264,44 C310,40 360,66 400,52" />
          <path d="M230,44 C214,24 188,28 191,43 C194,56 216,52 230,44 Z" />
          <path d="M230,44 C246,24 272,28 269,43 C266,56 244,52 230,44 Z" />
          <path d="M226,49 C219,60 211,65 204,62" />
          <path d="M234,49 C241,60 249,65 256,62" />
          <path d="M104,58 q9,7 19,3" />
          <path d="M180,44 q8,-8 17,-6" />
          <path d="M282,44 q-8,-8 -17,-6" />
          <path d="M356,58 q-9,7 -19,3" />
        </g>
        <circle cx="230" cy="44" r="5" :fill="BLUE" />
        <g v-for="f in FLOWERS" :key="f.x">
          <circle v-for="(p, i) in petals(f)" :key="i" :cx="p.cx" :cy="p.cy" :r="p.r" fill="#6987c3" />
          <circle :cx="f.x" :cy="f.y" :r="f.r * 0.45" :fill="BLUE" />
        </g>
      </svg>

      <!-- 底部花藤（镜像） -->
      <svg class="ornament ornament-bottom" viewBox="0 0 460 80" aria-hidden="true">
        <g transform="translate(0,80) scale(1,-1)">
          <g :stroke="BLUE" stroke-width="2.6" fill="none" stroke-linecap="round">
            <path d="M60,52 C40,62 22,54 26,41 C29,32 40,33 40,42 C40,49 32,51 28,47" />
            <path d="M60,52 C100,66 150,40 196,44" />
            <path d="M400,52 C420,62 438,54 434,41 C431,32 420,33 420,42 C420,49 428,51 432,47" />
            <path d="M264,44 C310,40 360,66 400,52" />
            <path d="M104,58 q9,7 19,3" />
            <path d="M180,44 q8,-8 17,-6" />
            <path d="M282,44 q-8,-8 -17,-6" />
            <path d="M356,58 q-9,7 -19,3" />
          </g>
          <g v-for="f in FLOWERS" :key="f.x">
            <circle v-for="(p, i) in petals(f)" :key="i" :cx="p.cx" :cy="p.cy" :r="p.r" fill="#6987c3" />
            <circle :cx="f.x" :cy="f.y" :r="f.r * 0.45" :fill="BLUE" />
          </g>
        </g>
      </svg>

      <!-- 绣字区：便签正文，逐字绣出 -->
      <div class="note-text">
        <template v-for="item in stitched" :key="item.id">
          <div v-if="item.type === 'nl'" class="nl"></div>
          <div v-else-if="item.type === 'cjk'" class="char-cell">
            <!-- 描红底稿：入队即刻可见，针随后沿底稿绣出 -->
            <span class="ghost" aria-hidden="true">{{ item.ch }}</span>
            <div :ref="setCellRef(item.id)" class="writer-host"></div>
          </div>
          <span v-else class="plain-ch" :style="{ color: item.color }">{{ item.ch }}</span>
        </template>
      </div>

      <!-- SVG 刺绣针：针尖在 (0,0)，跟随当前笔画 -->
      <div v-show="needleVisible" ref="needleEl" class="needle">
        <svg width="96" height="96" viewBox="-90 -86 96 96" class="needle-svg">
          <!-- 彩色绣线 -->
          <path
            d="M-33,-62 C-46,-76 -60,-64 -53,-51 C-48,-42 -38,-45 -41,-54 C-43,-61 -51,-60 -52,-54"
            fill="none" :stroke="threadColor" stroke-width="2.6" stroke-linecap="round"
          />
          <!-- 针鼻 -->
          <ellipse cx="-30.5" cy="-60" rx="3.2" ry="5.4" fill="none" stroke="#8d97a5" stroke-width="2.4"
            transform="rotate(-62 -30.5 -60)" />
          <!-- 针身 + 高光 -->
          <path d="M-28,-56 L0,0" stroke="#a9b2bf" stroke-width="5" stroke-linecap="round" />
          <path d="M-25,-52 L-3,-6" stroke="#dfe4eb" stroke-width="1.8" stroke-linecap="round" />
        </svg>
      </div>
    </div>

    <!-- 控制面板 -->
    <div class="panel">
      <label class="panel-title" for="type-input">
        <Icon name="needle" :size="16" />
        输入要绣的字（每打一个字，针就绣一个）
      </label>
      <input
        id="type-input"
        v-model="input"
        class="type-input"
        maxlength="40"
        placeholder="打字即刺绣，试试「我想你」"
        @compositionstart="composing = true"
        @compositionend="composing = false; onInput()"
        @input="onInput"
      />
      <div class="btns">
        <button class="btn" @click="randomNote"><Icon name="dice" /> 随机文案</button>
        <button class="btn" @click="replay"><Icon name="replay" /> 重播</button>
        <button class="btn" @click="copyText"><Icon name="copy" /> 复制</button>
        <button v-if="apiOk" class="btn primary" @click="generateImage"><Icon name="download" /> 生成图片</button>
        <button class="btn" @click="clearAll"><Icon name="trash" /> 清空</button>
      </div>
      <p class="status">{{ status }}</p>
    </div>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  padding: 7vh 16px 6vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 30px;
  background-color: #f2c7d2;
  background-image:
    radial-gradient(ellipse at 20% 10%, rgba(255, 255, 255, 0.18), transparent 55%),
    radial-gradient(ellipse at 80% 90%, rgba(214, 150, 165, 0.25), transparent 60%);
}

/* ---------------- 便签卡片（绣布） ---------------- */
.card {
  position: relative;
  width: min(92vw, 640px);
  background:
    repeating-linear-gradient(0deg, rgba(190, 178, 158, 0.07) 0 1px, transparent 1px 3px),
    repeating-linear-gradient(90deg, rgba(190, 178, 158, 0.07) 0 1px, transparent 1px 3px),
    #f7f3ea;
  box-shadow:
    0 16px 34px rgba(150, 85, 100, 0.35),
    0 4px 10px rgba(150, 85, 100, 0.22);
  padding: 64px 0 58px;
}

.card::before {
  /* 布纹噪点（不用 overflow:hidden 裁剪，避免把针剪掉） */
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  opacity: 0.4;
  mix-blend-mode: multiply;
  pointer-events: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3CfeComponentTransfer%3E%3CfeFuncA type='linear' slope='0.08'/%3E%3C/feComponentTransfer%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E");
}

.border-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.ornament {
  position: absolute;
  left: 50%;
  width: 68%;
  transform: translateX(-50%);
  pointer-events: none;
}
.ornament-top {
  top: 12px;
}
.ornament-bottom {
  bottom: 12px;
}

/* 绣字区：文字流式排布 */
.note-text {
  position: relative;
  z-index: 1;
  margin: 10px 13% 14px;
  min-height: 300px;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  align-content: flex-start;
  gap: 0 3px;
}

.char-cell {
  position: relative; /* 让底稿 .ghost 定位在本格子内 */
}

.char-cell,
.writer-host {
  width: 76px;
  height: 76px;
}

/* 描红底稿：排在绣层下面 */
.ghost {
  position: absolute;
  inset: 0;
  z-index: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'LXGW WenKai', 'Kaiti SC', 'STKaiti', 'KaiTi', serif;
  font-size: 52px;
  color: rgba(63, 95, 158, 0.16);
  user-select: none;
}

.writer-host {
  position: relative;
  z-index: 1;
}

.writer-host :deep(svg) {
  display: block;
}

.plain-ch {
  height: 76px;
  line-height: 84px;
  font-family: 'LXGW WenKai', 'Kaiti SC', 'STKaiti', 'KaiTi', serif;
  font-size: 40px;
  white-space: pre;
}

.nl {
  flex-basis: 100%;
  height: 0;
}

/* ---------------- 针（0×0 锚点 = 针尖，不溢出卡片右侧） ---------------- */
.needle {
  position: absolute;
  left: 0;
  top: 0;
  width: 0;
  height: 0;
  z-index: 5;
  pointer-events: none;
  will-change: transform;
}

.needle-svg {
  position: absolute;
  left: -90px;
  top: -86px;
  overflow: visible;
  animation: wobble 1.1s ease-in-out infinite;
  transform-origin: 90px 86px; /* 针尖处 */
}

@keyframes wobble {
  0%, 100% { transform: rotate(0deg); }
  50% { transform: rotate(-2.6deg); }
}

/* ---------------- 控制面板 ---------------- */
.panel {
  width: min(92vw, 640px);
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(6px);
  border-radius: 18px;
  padding: 16px 20px 12px;
  box-shadow: 0 8px 22px rgba(150, 85, 100, 0.2);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  color: #8a4a5c;
  margin-bottom: 10px;
  letter-spacing: 0.05em;
}

.type-input {
  width: 100%;
  border: 1.5px dashed rgba(63, 95, 158, 0.45);
  border-radius: 12px;
  padding: 11px 14px;
  font: inherit;
  font-size: 17px;
  color: #5a3a44;
  background: rgba(255, 255, 255, 0.75);
  outline: none;
}
.type-input:focus {
  border-color: #3f5f9e;
}

.btns {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.btn {
  flex: 1;
  min-width: 104px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 12px;
  font: inherit;
  font-size: 14.5px;
  color: #3f5f9e;
  background: #fff;
  border: 1.6px solid rgba(63, 95, 158, 0.5);
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn:hover {
  background: #eef2fb;
  transform: translateY(-1px);
}
.btn.primary {
  color: #fff;
  background: #3f5f9e;
  border-color: #3f5f9e;
}
.btn.primary:hover {
  background: #35508a;
}

.status {
  margin: 10px 0 2px;
  font-size: 13px;
  color: #a06e7d;
  text-align: center;
  min-height: 1.2em;
}
</style>
