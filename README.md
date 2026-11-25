# Video Creator Studio（个人自用全模态 AI 视频导演台）

对标 **MiniMax H3 / MiniMax Design** 创作流、基于 **Local-First + Google AI 全家桶（2026 Interactions API）** 的跨平台个人视频创作工作台：
- **左侧**：AI 导演对话（**Gemini 4** 看图理解现有资产 + 结构化分镜提案 + 人机确认防烧钱）
- **右侧五视图**：
  - **0. 小说拆集**：直接上传 `.txt`（兼容 UTF-8/GBK/GB18030）/ `.md` / `.docx` / `.epub` 整本小说或粘贴文本，自动识别章节与按字数分集；利用 **Gemini 4** 1M 长上下文提取**全书统一角色/场景/道具库（Book Bible）**；按集一键拆解为影视分镜
  - **1. 资产定妆库**：角色/场景/道具 + **Nano Banana 2.1** (`gemini-nano-banana-2.1`) 定妆与三视图（支持最多 14 张参考图融合）；支持批量上传图片/视频素材、FFmpeg `3s R2V` / `10s 编辑优化` / `剥离音轨` 裁剪、抽首尾帧
  - **2. 分镜故事板**：按分集筛选、**Gemini 4 AI 提示词扩写**、首尾帧合成与连贯、**Gemini Omni 1.2 Flash** / **Veo 3.1** 多版本抽卡（Takes）、**一键批量拍片（支持并行 / 自动尾帧接力）**、Take **多轮改片（Edit）与续写（Extend）**、Google Flow 25,000 积分桥接、Gemini 4 自动审片 QA
  - **3. 多轨时间线与导出**：按分集或全片组装、**Lyria 3.5** (`lyria-3.5`) 配乐、SRT 字幕生成与烧录、支持 `720p / 1080p / 4K` 与 **FFmpeg 柔和叠化转场（Crossfade）** 一键合片导出
  - **4. 全模态自由创作 / V2V**：独立 Omni 1.2 Flash 创作台（`3–15s`、`360p–4K`、`16:9 / 9:16`、最多 **6 张参考图 + 3 段参考视频 R2V**、首尾双帧过渡与同图无缝循环、外部视频剥音重配 V2V 改片、累计最高 `30s` 续写与**版本迭代谱系树**，支持一键将成品导入任意分镜镜头）
- **实时状态推送 & 零云端服务器费用**：SSE 实时推送后台任务进度；全部数据与视频保存在本地 `data/` 目录，顶部实时追踪本月 API 预估消耗与 Ultra 额度余额；未填 Key 时自动运行于 **Demo 本地演示模式**。

---

## 方式一：macOS / Linux 本地开发启动

```bash
chmod +x start.sh
./start.sh
```
- 前端工作台：`http://localhost:3000`
- 后端 API 文档：`http://127.0.0.1:8000/docs`
- 首次使用可点击右上角 **「设置」** 填入 `GEMINI_API_KEY` 并点击 **「测试连通性」**（将自动保存至根目录 `.env`）。

---

## 方式二：Windows 本地开发启动

1. 编辑根目录 `.env`（可选，未填自动进入 Demo 模式）。
2. 运行一键脚本：
   ```powershell
   .\start.ps1
   ```

---

## 方式三：Docker 一键部署（单容器前后端合一）

镜像采用多阶段构建（`Node 20` 编译前端 + `Python 3.11-slim` + 原生 `FFmpeg` + 文泉驿中文字体确保硬字幕不乱码），单容器对外提供完整服务，数据持久化挂载在宿主机 `./data`。

1. **准备配置**：
   ```bash
   cp .env.example .env
   # 编辑 .env 填入 GEMINI_API_KEY（不填也会自动以 Demo 模式启动，后续可在网页右上角「设置」中随时配置）
   ```
2. **构建并后台启动**：
   ```bash
   docker compose up -d --build
   ```
3. **打开工作台**：
   - 浏览器访问 `http://localhost:3000`（端口可在 `.env` 中通过 `STUDIO_PORT` 修改）
   - 健康检查：`http://localhost:3000/api/health`
   - 查看日志：`docker compose logs -f`

### Docker 进阶配置说明
- **网页端「设置」持久化**：你在网页右上角保存的 API Key / 模型 / 预算会写入持久化卷 `./data/runtime.env`，重建容器不会丢失。
- **接入 Vertex AI（Veo 3.1 正式版）**：
  1. 在项目根目录新建 `credentials/` 文件夹，放入你的 GCP 服务账号 JSON 文件（如 `service-account.json`）。
  2. 取消 `docker-compose.yml` 中 `- ./credentials:/credentials:ro` 的注释。
  3. 在 `.env` 中配置 `VERTEX_PROJECT_ID=你的项目ID` 与 `GOOGLE_APPLICATION_CREDENTIALS=/credentials/service-account.json`。
- **网络代理（国内 NAS / 服务器）**：如容器访问 Google API 需要代理，取消 `docker-compose.yml` 中 `HTTP_PROXY` / `HTTPS_PROXY` 注释并指向你的代理地址即可。

---

## 运行测试与构建校验

```bash
# 后端全量测试
cd apps/api && .venv/bin/pytest -v

# 前端类型检查与生产构建
cd apps/web && npm run build
```

---

## 领取 Google AI Ultra 开发者额度提示
1. 前往 [Google AI Studio](https://aistudio.google.com/) / Google Developer Program 后台领取每月 $40（Ultra 5x）或 $100（Ultra 20x）的云端开发者抵扣金并绑定结算账号。
2. 建议在 Google Cloud Billing 中设置与月额度一致的 **Budget Alert** 防超支。
3. 如需使用 Ultra 自带的 **25,000 Google Flow 网页端积分**，可在任意分镜卡片点击 **「复制 Flow 创作包」** 去 Flow 网页端免费生成 4K 素材，再直接拖回该镜头参与本地自动审片与 FFmpeg 合片。
