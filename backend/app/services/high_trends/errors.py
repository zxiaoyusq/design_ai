"""可公开的失败诊断；不保存网关响应正文、请求头或连接信息。"""

import re


def error_detail(exc: Exception, *, job_id=None, stage=None, attempt=None, seconds=None):
    """只提取确定的错误类别，未知异常不把可能含密钥的原始消息直接发到页面。"""
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    status = status if type(status) is int else None
    if "stream_read_error" in text:
        code, message = "stream_read_error", "模型接口在流式返回过程中报告读取错误，未取得完整结果。"
    elif "timeout" in type(exc).__name__.lower() or "timed out" in text:
        code, message = "model_timeout", "等待模型接口响应超时。"
    elif status == 429:
        code, message = "rate_limited", "模型接口限流，请稍后再继续。"
    elif status in {401, 403}:
        code, message = "authentication_failed", "模型接口认证或权限失败，请先检查服务配置。"
    elif status and status >= 500:
        code, message = "provider_error", "模型服务暂时不可用。"
    elif "connection" in type(exc).__name__.lower():
        code, message = "connection_error", "连接模型接口失败或连接中断。"
    elif "调用上限" in text:
        code, message = "call_budget_exceeded", "已达到本次调用上限，请调整上限后再继续。"
    else:
        code, message = "execution_error", "执行出现异常，请结合错误类型检查后端日志。"
    return {"code": code, "message": message,
            "exception_type": re.sub(r"[^A-Za-z0-9_]", "", type(exc).__name__)[:80],
            "http_status": status, "job_id": job_id, "stage": stage,
            "attempt": attempt, "seconds": round(seconds, 2) if seconds is not None else None}
