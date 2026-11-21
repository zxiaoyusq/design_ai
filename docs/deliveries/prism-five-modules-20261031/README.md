# 棱镜五模块交付 · DeepAgents / Gemini 版

交付日期：2026-10-31。新版本已替换本目录原源码 ZIP 与 Git bundle。

- `prism-five-modules-20261031.zip`：五模块源码、必要规则、部署与脱敏交接文档。解压后打开根目录 `index.html`。
- `prism-five-modules-20261031.bundle`：同一份独立 Git 分支，只有一个脱敏根提交。
- `SHA256SUMS`：两个文件的 SHA-256。
- `delivery-info.json`：提交、模型、文件数及安全核验记录。

所有模型执行入口统一使用 DeepAgents + 工程网关 SDK，新任务默认 `gemini-3.8-flash`。接收方自行配置密钥和管理员账号；包内没有原服务器密码、API Key、个人登录令牌或账号库。旧版文件已移出此交付目录，新 Git 备份不含旧版提交历史。

```bash
sha256sum -c SHA256SUMS
git clone -b codex/prism-five-modules-handoff-20261031 prism-five-modules-20261031.bundle prism-five-modules
```

提交：`38e83d0b3405eecf27f41e103206c31607ca3337`。

独立工作区：`/root/dev/work/design_ai-five-modules-20261031`。原工程分支及线上服务未切换。离线测试与五页面默认模型检查已通过；真实业务环境的 Gemini 权限、完整流程和效果仍需接收方配置后验证。
