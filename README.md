# Video Creator Studio（个人自用 AI 视频导演台）

对标 **MiniMax H3 / MiniMax Design** 创作流、基于 **Local-First + Google AI 全家桶** 的个人视频创作工作台：
- **左侧**：AI 导演对话（一句话拆解结构化分镜、对话修订镜头、防烧钱确认）
- **右侧四视图**：
  - **0. 小说拆集**：直接上传 `.txt`（兼容 UTF-8/GBK）/ `.md` / `.docx` / `.epub` 整本小说或粘贴文本，自动识别章节与按字数分集；利用 Gemini 长上下文提取**全书统一角色/场景库**；按集一键拆解为影视分镜
  - **1. 资产定妆库**：角色/场景/道具 + Nano Banana 2 生图与三视图
  - **2. 分镜故事板**：按分集筛选、关键帧融合、首尾帧连贯、Veo 3.1 / Omni Flash 多版本抽卡、Google Flow 25,000 积分桥接、Gemini 自动审片
  - **3. 多轨时间线与导出**：按分集或全片组装、Lyria 3 配乐、SRT 字幕、本地 FFmpeg 一键合片导出
- **零云端服务器费用**：全部数据与视频保存在本地 `data/` 目录，顶部实时追踪本月 API 预估消耗与 Ultra 额度余额。

## 快速启动（Windows）

1. **配置环境变量**：
   打开根目录的 `.env` 文件，填入 `GEMINI_API_KEY`（及可选的 `VERTEX_PROJECT_ID`）。
   > 未填密钥也可直接启动！系统在 `APP_MODE=auto` 下自动启用 **Demo 模式**（本地生成真实测试图片/视频并完整跑通 FFmpeg 合片），填入密钥后即自动切换为 **Live 模式**（也可在网页右上角「设置」中随时配置）。

2. **一键启动前后端**：
   ```powershell
   .\start.ps1
   ```
   - 前端工作台：`http://localhost:3000`
   - 后端 API 文档：`http://127.0.0.1:8000/docs`

## 领取 Google AI Ultra 开发者额度提示
1. 前往 [Google AI Studio](https://aistudio.google.com/) / Google Developer Program 后台领取每月 $40（Ultra 5x）或 $100（Ultra 20x）的云端开发者抵扣金并绑定结算账号。
2. 建议在 Google Cloud Billing 中设置与月额度一致的 **Budget Alert** 防超支。
3. 如需使用 Ultra 自带的 **25,000 Google Flow 网页端积分**，可在任意分镜卡片点击 **「复制 Flow 创作包」** 去 Flow 网页端免费生成 4K 素材，再直接拖回该镜头参与本地自动审片与 FFmpeg 合片。
