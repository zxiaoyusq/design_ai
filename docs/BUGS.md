# 未解决缺陷

## 2026-09-10：`tests.test_llm_api` 的 TestClient 请求超时

- 在当前 Python 3.14 / `314` 环境执行 `python -m unittest tests.test_llm_api -v` 时，首个 `TestClient(app).get("/api/v1/llm/models")` 超过 90 秒未返回；该问题未由本次 CORS 变更引入，仍需单独定位 TestClient 或其运行时依赖。
- 实际部署中的 `http://gamedevcenter.ahagamecenter.com/api/v1/llm/models` 已返回 200 和完整模型列表，因此当前不影响公网服务；启动脚本的实际启停与前端生产构建均已通过。
