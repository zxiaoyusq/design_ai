# AGENTS.md — AI 审美洞察平台开发规范

* 当任务存在两个以上互相独立的工作流 可以并行执行时，允许使用 Subagents。

## 1. 项目目标

建设 AI 审美洞察平台，包括以下核心链路：

> 图片上传 → 设计 DNA 提取 → 图片分类与索引 → 相似检索 → 方案契合度评分 → 结果展示与人工修订

## 2. 技术栈

### 前端

* Vue 3 + Vite + TypeScript
* Pinia、Vue Router、Axios
* Ant Design Vue
* 包管理统一使用 `pnpm`

### 后端

* Python 3.14：使用 **base** 这个conda 环境
* FastAPI + Pydantic
* SQLAlchemy + Alembic
* PostgreSQL 保存业务数据与结构化 DNA

### AI 与 Agent

* Agent 框架统一使用 **DeepAgents**
* 多模态大模型负责图片理解与 DNA 结构化提取

## 3. 工程结构

```text
frontend/
  src/
    api/
    components/
    views/
    stores/
    types/

backend/
  app/
    api/
    agents/
    tools/
    services/
    models/
    schemas/
    repositories/
  tests/

docs/
```

## 4. 开发规范
* 新增或修改的公共类型、公共接口、核心领域规则、非显然逻辑、边界条件应添加清晰的中文注释。不要为显而易见的赋值、分支或方法调用添加重复代码语义的注释。
* 遵循“少即是多”哲学。绝不进行不必要的抽象，绝不引入非必需的依赖。
* 反过度工程:简单的函数和数据结构优于复杂的接口和继承体系。
* 明确性原则 (Clarity and Explicitness)，代码的首要目的是让人类易于理解。
* 代码的编写应遵循SOLID原则。

## 5. Agent 执行原则

* 优先复用现有模块，避免重复建设。
* 涉及 DNA 修订、评分权重调整和数据写入时，保留人工确认入口。
* 所有模型结果必须可追溯到输入图片、模型版本、Prompt 版本和执行时间。

## 6. 完成时更新

* docs/PROGRESS.md
* 新增架构或生命周期决定时更新docs/DECISIONS.md
* 新增未解决缺陷时更新docs/BUGS.md
