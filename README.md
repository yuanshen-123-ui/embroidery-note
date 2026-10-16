# 刺绣便签 · Embroidery Note

粉色刺绣布贴风格的互动便签：**打字即刺绣** —— 每输入一个汉字，一根 SVG 刺绣针就带着彩色绣线，按真实笔顺把字一针一针"绣"在便签卡片上。

![效果预览](docs/preview.png)

- **前端**：Vue 3 + Vite + [hanzi-writer](https://hanziwriter.org/)。卡片、波浪刺绣边框、圆点、花藤蝴蝶结全部为手写 CSS / SVG，无图片素材。
- **后端（可选）**：Python FastAPI + Pillow。提供多套文案接口与"生成便签图片"接口；本地直供汉字笔画数据（hanzi-writer-data），不依赖 CDN。
- **纯静态也能跑**：没有后端时自动降级——文案用内置数据、笔画数据走 CDN 兜底链，可直接部署到 GitHub Pages。

## 快速开始

### 方式一：纯前端（GitHub Pages / 任意静态托管）

```bash
cd frontend
npm install
npm run build      # 产物在 frontend/dist，任意静态服务器可用
```

### 方式二：完整体验（本地后端）

```bash
# 1. 后端（端口 8000，自动托管前端构建产物 + 笔画数据）
cd backend
pip install -r requirements.txt
python main.py

# 2. 前端（开发模式，/api 已代理到 8000）
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:8000/`（构建产物）或 `http://127.0.0.1:5173/`（开发模式）。

## 刺绣针的实现原理

1. 每输入一个汉字，创建一个 `hanzi-writer` 实例，`animateStroke(i, { onComplete })` 从第 0 笔开始逐笔播放；
2. `hanzi-writer` 的字符数据里每笔有一条 `medians` 运笔中线——把它按**弧长均匀重采样**成点序列；
3. 针的动画时长与 hanzi-writer 完全同源：`(path.getTotalLength() + 600) / (3 × strokeAnimationSpeed)`，`requestAnimationFrame` 按进度取点，二者同步走完；
4. `HanziWriter.getScalingTransform()` 做数据坐标 → 屏幕坐标转换。注意其 transform 为 `translate(x, H−y) scale(s, −s)`（数据坐标 `x∈[0,1024]`、`y∈[−124,900]`，y 轴朝上），因此 `screen = (x + s·px, (H−y) − s·py)`；
5. 针位置每帧用 `transform: translate()` 更新（绕过 Vue 响应式）；一个字绣完，针直线滑到下一个字的第一笔起点。

## API（有后端时）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/notes` | 文案列表（多套，在 `backend/main.py` 的 `NOTES` 中增删） |
| GET | `/api/notes/random` | 随机一条文案 |
| GET | `/api/notes/{id}` | 指定文案 |
| GET | `/hanzi-data/{char}.json` | 汉字笔画数据（hanzi-writer-data，MIT） |
| POST | `/api/render` | Pillow 渲染便签 PNG。body: `{text, width, height, seed, font_size}`；`?download=1` 触发下载 |

## 自定义

- **文案库**：`backend/main.py` 的 `NOTES`；无后端时用 `frontend/src/components/EmbroideryNote.vue` 里的 `LOCAL_NOTES` 兜底。
- **绣线颜色**：组件里的 `PALETTE`（六色轮换）。
- **字体**：便签文字与图标字体均可换，推荐开源的[霞鹜文楷 LXGW WenKai](https://github.com/lxgw/LxgwWenKai)。
- **笔画数据离线化**：`npm i hanzi-writer-data` 后把 JSON 拷进 `backend/hanzi-data/`（仓库已忽略该目录，脚本见下）。

```bash
npm i -D hanzi-writer-data
mkdir -p backend/hanzi-data
cp node_modules/hanzi-writer-data/*.json backend/hanzi-data/
```

## 参考的开源项目

- [chanind/hanzi-writer](https://github.com/chanind/hanzi-writer) — 汉字笔顺动画引擎（MIT）
- [chanind/hanzi-writer-data](https://github.com/chanind/hanzi-writer-data) — 汉字笔画/中线数据（MIT，源自 makemeahanzi）
- [HaujetZhao/QuickHand](https://github.com/HaujetZhao/QuickHand) — 仿手写文字图片生成器
- [zxw1992/text2card](https://github.com/zxw1992/text2card) — 文本转精美分享卡片
- [lxgw/LxgwWenKai](https://github.com/lxgw/LxgwWenKai) — 开源中文字体霞鹜文楷（SIL OFL）

## License

MIT
