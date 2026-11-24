# Video Creator Studio（个人自用 AI 视频导演台）

对标 **MiniMax H3 / MiniMax Design** 创作流、基于 **Local-First + Google AI 全家桶** 的个人视频创作工作台：
- **左侧**：AI 导演对话（一句话拆解结构化分镜、对话修订镜头、防烧钱确认）
- **右侧四视图**：
  - **0. 小说拆集**：直接上传 `.txt`（兼容 UTF-8/GBK）/ `.md` / `.docx` / `.epub` 整本小说或粘贴文本，自动识别章节与按字数分集；利用 Gemini 长上下文提取**全书统一角色/场景库**；按集一键拆解为影视分镜
  - **1. 资产定妆库**：角色/场景/道具 + Nano Banana 2 生图与三视图
  - **2. 分镜故事板**：按分集筛选、关键帧融合、首尾帧连贯、Veo 3.1 / Omni Flash 多版本抽卡、Google Flow 25,000 积分桥接、Gemini 自动审片
  - **3. 多轨时间线与导出**：按分集或全片组装、Lyria 3 配乐、SRT 字幕、本地 FFmpeg 一键合片导出
- **零云端服务器费用**：全部数据与视频保存在本地 `data/` 目录，顶部实时追踪本月 API 预估消耗与 Ultra 额度余额。

---

## 方式一：Docker 一键部署（推荐 · 单容器前后端合一）

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

## 方式二：Windows 本地开发启动

1. 编辑根目录 `.env`（可选，未填自动进入 Demo 模式）。
2. 运行一键脚本：
   ```powershell
   .\start.ps1
   ```
   - 前端工作台：`http://localhost:3000`
   - 后端 API 文档：`http://127.0.0.1:8000/docs`

---

## 领取 Google AI Ultra 开发者额度提示
1. 前往 [Google AI Studio](https://aistudio.google.com/) / Google Developer Program 后台领取每月 $40（Ultra 5x）或 $100（Ultra 20x）的云端开发者抵扣金并绑定结算账号。
2. 建议在 Google Cloud Billing 中设置与月额度一致的 **Budget Alert** 防超支。
3. 如需使用 Ultra 自带的 **25,000 Google Flow 网页端积分**，可在任意分镜卡片点击 **「复制 Flow 创作包」** 去 Flow 网页端免费生成 4K 素材，再直接拖回该镜头参与本地自动审片与 FFmpeg 合片。
