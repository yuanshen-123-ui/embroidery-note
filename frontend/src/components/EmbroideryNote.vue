<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from './Icon.vue'

/* ---------------- 常量 ---------------- */
const CELL = 76           // 单字格子
const PAD = 4
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
const stitched = ref([])        // { id, ch, color, type: 'cjk'|'plain'|'nl', rot, dy }
const notes = ref(LOCAL_NOTES)
const apiOk = ref(false)        // 后端可达时才显示"生成图片"
const status = ref('')
const threadColor = ref(PALETTE[0])
const needleVisible = ref(false)

/* 工具栏状态 */
const threadMode = ref('auto')  // 'auto' 或具体颜色
const pickerOpen = ref(false)
const fontIdx = ref(0)
const FONTS = [
  // 手写：本地版注入 hiJessieHW（作者仅授权个人使用，字体文件不进仓库/不上 Pages）；
  // 若系统装过该字体则 hit 名字 hiJessie1；公开站点回退开源手写体
  { name: '手写', css: "'hiJessieHW', 'hiJessie1', 'Ma Shan Zheng', 'LXGW WenKai', 'Kaiti SC', 'KaiTi', serif" },
  { name: '善政', css: "'Ma Shan Zheng', 'hiJessieHW', 'LXGW WenKai', 'KaiTi', serif" },
  { name: '龙藏', css: "'Long Cang', 'hiJessieHW', 'LXGW WenKai', 'KaiTi', serif" },
  { name: '文楷', css: "'LXGW WenKai', 'Kaiti SC', 'STKaiti', 'KaiTi', serif" },
]
const handFont = computed(() => FONTS[fontIdx.value].css)
const customColor = ref('#3f5f9e')

const cardEl = ref(null)
const needleEl = ref(null)
const threadPathEl = ref(null)
const ballEl = ref(null)
const cushionEl = ref(null)
const ballCenter = { x: 0, y: 0 }
let pending = 0 // 待绣字数：归零时针回收进针插

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

/* 手写歪斜内联样式（汉字格 / 普通字符共用） */
function tiltStyle(item) {
  return { transform: `rotate(${item.rot}deg) translateY(${item.dy}px)` }
}

/* ---------------- 笔画数据：同源优先，CDN 多级兜底 ---------------- */
const DATA_SOURCES = [
  'hanzi-data/',                                              // 本地后端 / 自托管 / Pages 同源
  'https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0/',
  'https://fastly.jsdelivr.net/npm/hanzi-writer-data@2.0/',
  'https://unpkg.com/hanzi-writer-data@2.0/',
]
async function fetchCharData(ch, isAborted) {
  if (dataCache.has(ch)) return dataCache.get(ch)
  const name = encodeURIComponent(ch) + '.json'
  let lastErr
  for (const base of DATA_SOURCES) {
    if (isAborted && isAborted()) throw new Error('cancelled')
    try {
      const res = await fetch(base + name, { signal: AbortSignal.timeout(4000) })
      if (!res.ok) throw new Error(String(res.status))
      const data = await res.json()
      if (!data.strokes || !data.medians) throw new Error('bad data')
      dataCache.set(ch, data)
      return data
    } catch (e) {
      if (isAborted && isAborted()) throw new Error('cancelled')
      lastErr = e
    }
  }
  throw lastErr
}

/* ---------------- 针驱动：直接写 transform，绕过响应式开销 ---------------- */
function setNeedle(x, y) {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return // 防御：异常坐标不污染针/拖线
  needlePos.x = x
  needlePos.y = y
  if (needleEl.value) {
    needleEl.value.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`
  }
  /* 针鼻拖着长线连到右下角的线球（贝塞尔自然下垂） */
  if (threadPathEl.value) {
    const ex = x - 30
    const ey = y - 60
    const bx = ballCenter.x
    const by = ballCenter.y
    threadPathEl.value.setAttribute(
      'd',
      `M ${ex.toFixed(1)} ${ey.toFixed(1)} C ${(ex - 12).toFixed(1)} ${(ey + 60).toFixed(1)}, ${(bx - 40).toFixed(1)} ${(by - 55).toFixed(1)}, ${bx.toFixed(1)} ${by.toFixed(1)}`,
    )
  }
}

/* 沿等弧长采样点按进度取点（rAF + 线性插值，与 hanzi-writer 同步）
   注意：rAF 帧时间戳可能早于 t0（vsync 对齐），必须把进度钳制在 [0,1]，
   否则负索引会让整个播放队列崩溃 —— 这正是"针不动/画不出"的元凶 */
function animateAlong(pts, ms, gen, aborted) {
  return new Promise((resolve) => {
    const t0 = performance.now()
    const safeMs = Number.isFinite(ms) && ms > 0 ? ms : 400
    const step = (now) => {
      if (gen !== playGen || (aborted && aborted())) return resolve()
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
function glide(target, ms, gen, aborted) {
  return animateAlong([[needlePos.x, needlePos.y], [target.x, target.y]], ms, gen, aborted)
}

/* 中断某个字的动画：置取消标记，唤醒播放循环（渲染已改为 CSS 描边，无需操作 writer） */
function stopWriter(item) {
  item.cancelled = true
  try {
    item.onCancel?.()
  } catch {}
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/* 等价 hanzi-writer getScalingTransform 的坐标变换：
   字符数据包围盒 x∈[0,1024]、y∈[−124,900]（y 轴朝上），
   返回 {x, y, scale}，屏幕坐标 = (x + s·px, (H−y) − s·py) */
function scalingTransform(width, height, padding) {
  const PRE = 1024
  const effW = width - 2 * padding
  const effH = height - 2 * padding
  const scale = Math.min(effW / PRE, effH / PRE)
  const x = padding + (effW - scale * PRE) / 2
  const y = 124 * scale + padding + (effH - scale * PRE) / 2
  return { x, y, scale }
}

/* 收针：队列空了，针滑回右上角针插里插着（防重入） */
let parking = false
function maybePark(gen) {
  if (parking) return
  parking = true
  parkNeedle(gen).finally(() => {
    parking = false
  })
}
async function parkNeedle(gen) {
  await nextTick()
  const cushion = cushionEl.value
  const card = cardEl.value
  if (!cushion || !card || gen !== playGen) return
  const br = cushion.getBoundingClientRect()
  const cr = card.getBoundingClientRect()
  await glide(
    { x: br.left - cr.left + br.width * 0.52, y: br.top - cr.top + br.height * 0.42 },
    420,
    gen,
  )
  status.value = '收针 ✧ 布面等你下一句'
}

/* ---------------- 逐字绣制 ---------------- */
async function playItem(item, gen) {
  if (item.type === 'nl') return
  await nextTick()
  if (item.cancelled) return
  const host = cellEls.get(item.id)
  const card = cardEl.value
  if (!host || !card || gen !== playGen) return
  const dead = () => item.cancelled || gen !== playGen

  /* 线球锚点（相对卡片坐标，每次开播刷新一次） */
  if (ballEl.value) {
    const br = ballEl.value.getBoundingClientRect()
    const cr = card.getBoundingClientRect()
    ballCenter.x = br.left - cr.left + 12
    ballCenter.y = br.top - cr.top + 14
  }

  /* 格子原点：用 offset 链取"未旋转"的布局位置（transform 不影响 offsetLeft/Top） */
  let ox = 0
  let oy = 0
  let el = host
  while (el && el !== card) {
    ox += el.offsetLeft
    oy += el.offsetTop
    el = el.offsetParent
  }

  /* 非汉字：针跳到格子中央，直接以彩色文字呈现 */
  if (item.type !== 'cjk') {
    threadColor.value = item.color
    needleVisible.value = true
    await glide({ x: ox + CELL / 2, y: oy + CELL / 2 + (item.dy || 0) }, 240, gen, () => item.cancelled)
    return
  }

  /* 笔画数据仅用于针的走针路线（medians）；字形改用"手写字体 + CSS 描边动画"渲染，
     这样字体跟随 font-family，而不再受 hanzi-writer 内置 SVG 路径限制 */
  let data
  try {
    data = await fetchCharData(item.ch, () => item.cancelled || gen !== playGen)
  } catch {
    if (dead()) return // 删除回退已触发：不再做任何兜底动作
    item.type = 'plain' // 数据不可得（如离线）：回退彩色文字
    threadColor.value = item.color
    needleVisible.value = true
    await glide({ x: ox + CELL / 2, y: oy + CELL / 2 + (item.dy || 0) }, 240, gen, () => item.cancelled)
    return
  }
  if (dead()) return

  /* 数据坐标 → 格内坐标（等价 hanzi-writer getScalingTransform，y 翻转），
     再叠加与 CSS 一致的格子旋转 rotate(rot) translateY(dy)，让针贴住歪斜后的字形 */
  const st = scalingTransform(CELL, CELL, PAD)
  const ty = CELL - st.y
  const th = ((item.rot || 0) * Math.PI) / 180
  const cos = Math.cos(th)
  const sin = Math.sin(th)
  const dyv = item.dy || 0
  const ccx = CELL / 2
  const ccy = CELL / 2
  const toScreen = (p) => {
    const x = st.x + st.scale * p[0]
    const y = ty - st.scale * p[1]
    const rx = (x - ccx) * cos - (y - ccy) * sin - sin * dyv
    const ry = (x - ccx) * sin + (y - ccy) * cos + cos * dyv
    return [ox + ccx + rx, oy + ccy + ry]
  }

  /* 针走全部笔画中线（拼接成一条连续针路），总时长 1.5–2s；
     字形描边动画（stroke-dashoffset）用同一个 --dur，二者同屏同步 */
  const allPts = []
  for (const m of data.medians) allPts.push(...resampleByArc(m).map(toScreen))
  if (!allPts.length) {
    item.type = 'plain'
    return
  }
  const dur = 1500 + Math.random() * 350
  host.style.setProperty('--dur', `${dur | 0}ms`)
  host.classList.add('stitch')

  threadColor.value = item.color
  needleVisible.value = true

  /* 上一字绣完 → 针滑到本字针路起点 */
  await glide(allPts[0], 340, gen, () => item.cancelled)
  if (dead()) return

  status.value = `「${item.ch}」走针中`
  setNeedle(allPts[0][0], allPts[0][1])
  const cancelSig = new Promise((res) => {
    item.onCancel = res
  })
  const needleDone = animateAlong(allPts, dur, gen, () => item.cancelled)
  await Promise.race([
    Promise.all([sleep(dur), needleDone]),
    cancelSig,
    sleep(dur + 3000),
  ])
  if (item.cancelled || gen !== playGen) return
  setNeedle(allPts[allPts.length - 1][0], allPts[allPts.length - 1][1])
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
      : {
          id: ++uid,
          ch,
          color:
            threadMode.value !== 'auto'
              ? threadMode.value
              : PALETTE[colorIdx++ % PALETTE.length],
          type: IS_CJK(ch) ? 'cjk' : 'plain',
          // 手写歪斜：每字独立随机，重播/刷新时重新生成
          rot: (3 + Math.random() * 5) * (Math.random() < 0.5 ? -1 : 1), // ±3–8°
          dy: (2 + Math.random() * 2) * (Math.random() < 0.5 ? -1 : 1),  // ±2–4px
        }
    stitched.value.push(item)
    if (item.type !== 'nl') {
      pending++
      item.counted = true
      const gen = playGen
      chain = chain
        .then(() => playItem(item, gen))
        .catch(() => {})
        .then(() => {
          if (item.counted) {
            item.counted = false
            pending = Math.max(0, pending - 1)
          }
          if (pending === 0 && needleVisible.value) maybePark(gen)
        })
    }
  }
}

function onInput() {
  if (composing.value) return
  const v = input.value
  if (v.length > prevLen) {
    enqueueText(v.slice(prevLen))
  } else if (v.length < prevLen) {
    /* 退格/删除：从绣布尾部移除对应数量的字（中断动画 + 清理实例 + 同步针） */
    removeLast(prevLen - v.length)
  }
  prevLen = v.length
}
/* 输入框为空但布面有字时，Backspace 直接剪布上的字 */
function onBackspace(e) {
  if (!input.value.length && stitched.value.length) {
    removeLast(1)
    e.preventDefault()
  }
}
const composing = ref(false)

/* 删除回退：移除布面尾部 n 个字（正在绣的立即中断，未绣的直接出队） */
function removeLast(n = 1) {
  const removed = []
  for (let k = 0; k < n && stitched.value.length; k++) {
    const item = stitched.value.pop()
    removed.push(item)
    if (item.type === 'nl') continue
    stopWriter(item) // 置 cancelled + 中断 animateStroke + 清理 writer
    if (item.counted) {
      item.counted = false // 还没轮到它播，出队
      pending = Math.max(0, pending - 1)
    }
  }
  if (removed.length) {
    status.value =
      removed.length === 1 ? `剪掉了「${removed[0].ch}」` : `剪掉了 ${removed.length} 个字`
    if (pending === 0 && needleVisible.value) maybePark(playGen)
  }
  return removed
}

function clearAll() {
  playGen++
  stitched.value.forEach(stopWriter) // 中断所有在播/排队动画
  chain = Promise.resolve()
  pending = 0
  stitched.value = []
  input.value = ''
  prevLen = 0
  needleVisible.value = false
  status.value = '已清空，重新开始吧'
}

function replay() {
  const seq = stitched.value.map((t) => t.ch).join('')
  playGen++
  stitched.value.forEach(stopWriter)
  chain = Promise.resolve()
  pending = 0
  stitched.value = []
  needleVisible.value = false
  enqueueText(seq)
}

async function randomNote() {
  const pool = notes.value.length ? notes.value : LOCAL_NOTES
  const note = pool[Math.floor(Math.random() * pool.length)]
  playGen++
  stitched.value.forEach(stopWriter)
  chain = Promise.resolve()
  pending = 0
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

/* ---------------- 工具栏：绣线 / 字体 / 图案 / 粘贴 / 剪刀 ---------------- */
function togglePicker() {
  pickerOpen.value = !pickerOpen.value
}
function pickColor(c) {
  threadMode.value = c
  threadColor.value = c // 拖线立即换色
  status.value = '已换绣线'
}
function cycleFont() {
  fontIdx.value = (fontIdx.value + 1) % FONTS.length
  status.value = `字体：${FONTS[fontIdx.value].name}`
}
function insertPattern() {
  const syms = ['♡', '✿', '★', '☆', '❀', '♥']
  enqueueText(syms[Math.floor(Math.random() * syms.length)])
}
async function pasteText() {
  try {
    const t = await navigator.clipboard.readText()
    if (!t) throw new Error('empty')
    enqueueText(t.slice(0, MAX_CHARS))
    status.value = '已粘贴，开绣'
  } catch {
    status.value = '读取剪贴板失败，请 Ctrl+V 到输入框'
  }
}
function cutLast() {
  removeLast(1)
}

async function generateImage() {  try {
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
  /* 不自动开绣：空布面等待用户输入 */
  const isStaticHost = /\.github\.io$|\.gitee\.io$/.test(location.hostname)
  /* 本地版注入手写字体（字体文件 public/fonts 已被 gitignore，仓库/Pages 不含它；
     作者声明仅个人使用，故只在本地使用，不公开分发） */
  if (!isStaticHost) {
    try {
      const probe = await fetch('fonts/hiJessie1.otf', { method: 'HEAD', signal: AbortSignal.timeout(1500) })
      if (probe.ok) {
        const st = document.createElement('style')
        st.textContent =
          "@font-face{font-family:'hiJessieHW';src:url('fonts/hiJessie1.otf') format('opentype');font-display:swap}"
        document.head.appendChild(st)
      }
    } catch {
      /* 字体不存在则用回退字体 */
    }
  }
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

/* 布面毛边：四边伸出的布丝（模块加载时生成一次） */
const frayLines = []
{
  const n = 26
  for (let i = 0; i < n; i++) {
    const t = 30 + (i + Math.random() * 0.7) * (660 / n)
    const l = 4 + Math.random() * 9
    const j = Math.random() * 6 - 3
    frayLines.push({ x1: t.toFixed(1), y1: 2, x2: (t + j).toFixed(1), y2: (-l).toFixed(1) })
    frayLines.push({ x1: t.toFixed(1), y1: 732, x2: (t + j).toFixed(1), y2: (732 + l).toFixed(1) })
    const v = 30 + (i + Math.random() * 0.7) * (674 / n)
    frayLines.push({ x1: 2, y1: v.toFixed(1), x2: (-l).toFixed(1), y2: (v + j).toFixed(1) })
    frayLines.push({ x1: 718, y1: v.toFixed(1), x2: (718 + l).toFixed(1), y2: (v + j).toFixed(1) })
  }
}
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
    <div ref="cardEl" class="card" :style="{ '--hand-font': handFont }">
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
        <div v-if="!stitched.length" class="empty-hint">
          在下方输入文字，就开始一针一针绣出来 ✧
        </div>
        <template v-for="item in stitched" :key="item.id">
          <div v-if="item.type === 'nl'" class="nl"></div>
          <div
            v-else-if="item.type === 'cjk'"
            class="char-cell"
            :style="tiltStyle(item)"
          >
            <!-- 描红底稿：入队即刻可见，随后手写字体描边覆盖 -->
            <span class="ghost" aria-hidden="true">{{ item.ch }}</span>
            <div :ref="setCellRef(item.id)" class="writer-host">
              <svg class="writer-svg" viewBox="0 0 76 76" aria-hidden="true">
                <text class="stroke-text" x="38" y="41" text-anchor="middle" dominant-baseline="central" :style="{ color: item.color }">{{ item.ch }}</text>
              </svg>
            </div>
          </div>
          <span
            v-else
            class="plain-ch"
            :style="{ color: item.color, transform: `rotate(${item.rot}deg) translateY(${item.dy}px)` }"
          >{{ item.ch }}</span>
        </template>
      </div>

      <!-- 布面毛边（抽丝） -->
      <svg class="fray-svg" viewBox="0 0 720 734" preserveAspectRatio="none" aria-hidden="true">
        <line
          v-for="(l, i) in frayLines" :key="'f' + i" v-bind="l"
          :stroke="i % 2 ? 'rgba(255,255,255,.85)' : 'rgba(212,200,178,.75)'" stroke-width="1.4"
        />
      </svg>

      <!-- 针插（空闲时针收回这里） -->
      <div ref="cushionEl" class="pincushion" aria-hidden="true">
        <svg viewBox="0 0 60 46" width="58" height="44">
          <ellipse cx="30" cy="31" rx="26" ry="14" fill="#e895a6" />
          <path d="M6 27 Q30 7 54 27" fill="none" stroke="#d67c90" stroke-width="2" />
          <path d="M12 22 Q30 37 48 22" fill="none" stroke="#d67c90" stroke-width="2" />
          <ellipse cx="30" cy="27" rx="4.5" ry="2.8" fill="#c96a80" />
          <line x1="20" y1="25" x2="13" y2="7" stroke="#a9b2bf" stroke-width="2" />
          <circle cx="13" cy="6" r="2.4" fill="#5b8fd6" />
          <line x1="40" y1="25" x2="47" y2="8" stroke="#a9b2bf" stroke-width="2" />
          <circle cx="47" cy="7" r="2.4" fill="#5aa86e" />
        </svg>
      </div>

      <!-- 针鼻拖线（连到右下角线球） -->
      <svg class="thread-layer" v-show="needleVisible" aria-hidden="true">
        <path
          ref="threadPathEl" d="" fill="none" :stroke="threadColor"
          stroke-width="2.2" stroke-linecap="round" opacity="0.85"
        />
      </svg>

      <!-- 彩色线球 -->
      <div ref="ballEl" class="yarn" aria-hidden="true">
        <svg viewBox="0 0 48 48" width="46" height="46">
          <defs><clipPath id="yarnclip"><circle cx="24" cy="24" r="20" /></clipPath></defs>
          <circle cx="24" cy="24" r="20" fill="#8a6fc0" />
          <g clip-path="url(#yarnclip)" fill="none" stroke-width="5" stroke-linecap="round">
            <path d="M0 13 Q24 21 48 11" stroke="#5b8fd6" />
            <path d="M0 25 Q24 33 48 23" stroke="#5aa86e" />
            <path d="M0 37 Q24 43 48 35" stroke="#d16a8a" />
          </g>
          <ellipse cx="16" cy="15" rx="5.5" ry="3" fill="rgba(255,255,255,.35)" transform="rotate(-24 16 15)" />
        </svg>
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
      <!-- 工具瓦片栏 -->
      <div class="toolbar">
        <button class="tile" :class="{ on: pickerOpen }" @click="togglePicker">
          <span class="tile-icon t1"><Icon name="spool" :size="20" /></span><span class="tile-label">绣线</span>
        </button>
        <button class="tile" @click="cycleFont">
          <span class="tile-icon t2"><Icon name="font" :size="20" /></span><span class="tile-label">{{ FONTS[fontIdx].name }}</span>
        </button>
        <button class="tile" @click="insertPattern">
          <span class="tile-icon t3"><Icon name="flower" :size="20" /></span><span class="tile-label">图案</span>
        </button>
        <button class="tile" @click="pasteText">
          <span class="tile-icon t4"><Icon name="paste" :size="20" /></span><span class="tile-label">粘贴</span>
        </button>
        <button class="tile" @click="cutLast">
          <span class="tile-icon t5"><Icon name="scissors" :size="20" /></span><span class="tile-label">剪刀</span>
        </button>
        <button class="tile" @click="randomNote">
          <span class="tile-icon t6"><Icon name="dice" :size="20" /></span><span class="tile-label">随机</span>
        </button>
        <button class="tile" @click="replay">
          <span class="tile-icon t7"><Icon name="replay" :size="20" /></span><span class="tile-label">重播</span>
        </button>
        <button class="tile" @click="generateImage">
          <span class="tile-icon t8"><Icon name="download" :size="20" /></span><span class="tile-label">保存</span>
        </button>
        <button class="tile" @click="clearAll">
          <span class="tile-icon t9"><Icon name="trash" :size="20" /></span><span class="tile-label">清空</span>
        </button>
      </div>

      <!-- 绣线色盘 -->
      <div v-if="pickerOpen" class="swatches">
        <button class="swatch auto" :class="{ on: threadMode === 'auto' }" @click="threadMode = 'auto'">随机</button>
        <button
          v-for="c in PALETTE" :key="c" class="swatch"
          :class="{ on: threadMode === c }" :style="{ background: c }" @click="pickColor(c)"
        ></button>
        <label class="swatch custom" title="自定义线色">
          <input type="color" v-model="customColor" @input="pickColor(customColor)" />
        </label>
      </div>

      <input
        id="type-input"
        v-model="input"
        class="type-input"
        maxlength="40"
        placeholder="打字即刺绣，试试「我想你」"
        @compositionstart="composing = true"
        @compositionend="composing = false; onInput()"
        @input="onInput"
        @keydown.delete="onBackspace"
      />
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

.char-cell {
  width: 76px;
  height: 76px;
}

/* 描红底稿：排在描边层下面 */
.ghost {
  position: absolute;
  inset: 0;
  z-index: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--hand-font, 'LXGW WenKai', 'Kaiti SC', 'STKaiti', 'KaiTi', serif);
  font-size: 52px;
  color: rgba(63, 95, 158, 0.16);
  user-select: none;
}

/* 手写字体描边层（div 锚点 + 内部 SVG text，跟随 font-family） */
.writer-host {
  position: relative;
  z-index: 1;
  width: 76px;
  height: 76px;
}

.writer-svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}

/* 描边动画：stroke-dashoffset 逐段"写"出，末段填充成实色绣线 */
.stroke-text {
  font-family: var(--hand-font, 'LXGW WenKai', 'Kaiti SC', 'STKaiti', 'KaiTi', serif);
  font-size: 54px;
  stroke: currentColor;
  fill: currentColor;
  fill-opacity: 0;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 800;
  stroke-dashoffset: 800;
}

.writer-host.stitch .stroke-text {
  animation:
    write-on var(--dur, 1700ms) linear forwards,
    fill-in calc(var(--dur, 1700ms) * 0.4) ease-out calc(var(--dur, 1700ms) * 0.6) forwards;
}

@keyframes write-on {
  from { stroke-dashoffset: 800; fill-opacity: 0; }
  to { stroke-dashoffset: 0; fill-opacity: 0; }
}

@keyframes fill-in {
  from { fill-opacity: 0; }
  to { fill-opacity: 1; }
}

.empty-hint {
  color: rgba(63, 95, 158, 0.35);
  font-size: 17px;
  letter-spacing: 0.1em;
  align-self: center;
  width: 100%;
  text-align: center;
  padding-top: 90px;
  user-select: none;
}

.plain-ch {
  height: 76px;
  line-height: 84px;
  font-family: var(--hand-font, 'LXGW WenKai', 'Kaiti SC', 'STKaiti', 'KaiTi', serif);
  font-size: 40px;
  white-space: pre;
  /* 非中文：打字机式擦除 + 淡入（clip-path 不影响歪斜 transform） */
  animation: type-in 300ms ease-out both;
}

@keyframes type-in {
  from {
    opacity: 0;
    clip-path: inset(-30% 100% -30% 0);
  }
  to {
    opacity: 1;
    clip-path: inset(-30% 0 -30% 0);
  }
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

/* 针鼻拖线层（连到线球） */
.thread-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 4;
  pointer-events: none;
}

/* 彩色线球（右下角，可略微探出布面） */
.yarn {
  position: absolute;
  right: 34px;
  bottom: -24px;
  z-index: 4;
  filter: drop-shadow(0 4px 8px rgba(120, 60, 80, 0.3));
}

/* 针插（右上角，压着布边） */
.pincushion {
  position: absolute;
  right: 46px;
  top: -16px;
  z-index: 6;
  filter: drop-shadow(0 3px 6px rgba(120, 60, 80, 0.28));
}

/* 布面毛边 */
.fray-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
  z-index: 0;
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

/* ---------------- 工具瓦片栏 ---------------- */
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 4px;
  margin-bottom: 10px;
}

.tile {
  flex: 1;
  min-width: 58px;
  max-width: 78px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: none;
  padding: 2px 0;
  cursor: pointer;
  font: inherit;
}

.tile-icon {
  width: 44px;
  height: 44px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6b5560;
  background: #fde3ec;
  box-shadow:
    0 2px 5px rgba(150, 85, 100, 0.16),
    inset 0 0 0 2px rgba(255, 255, 255, 0.65);
  transition: transform 0.12s ease;
}

.tile:hover .tile-icon {
  transform: translateY(-2px);
}
.tile:active .tile-icon {
  transform: scale(0.93);
}
.tile.on .tile-icon {
  outline: 2px solid #3f5f9e;
}

.t1 { background: #dce9fb; }
.t2 { background: #fde3ec; }
.t3 { background: #e6def7; }
.t4 { background: #ddf2e3; }
.t5 { background: #fdf0d9; }
.t6 { background: #fce9e2; }
.t7 { background: #e2f0fa; }
.t8 { background: #f3e6f7; }
.t9 { background: #fbe6e6; }

.tile-label {
  font-size: 12px;
  color: #8a5a68;
  letter-spacing: 0.05em;
}

/* ---------------- 绣线色盘 ---------------- */
.swatches {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: -2px 0 10px;
}

.swatch {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
  cursor: pointer;
  font: inherit;
  font-size: 10px;
  color: #fff;
  padding: 0;
}
.swatch.on {
  outline: 2.5px solid #3f5f9e;
  outline-offset: 2px;
}
.swatch.auto {
  background: conic-gradient(#c0504d, #d16a8a, #8455a8, #3f5f9e, #4f8a54, #7ea13f, #c0504d);
  font-weight: 700;
}
.swatch.custom {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
}
.swatch.custom input {
  position: absolute;
  inset: -8px;
  opacity: 0;
  cursor: pointer;
}

.status {
  margin: 10px 0 2px;
  font-size: 13px;
  color: #a06e7d;
  text-align: center;
  min-height: 1.2em;
}
</style>
