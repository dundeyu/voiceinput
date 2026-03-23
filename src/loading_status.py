"""启动阶段状态文案 helper。"""


def format_loading_status(step: int, total: int, text: str) -> str:
    """将阶段信息格式化为带进度条的状态文案。"""
    if total <= 0:
        return text

    current = max(0, min(step, total))
    filled = current
    empty = total - current
    bar = f"[{'#' * filled}{'-' * empty}]"
    return f"{bar} {current}/{total} {text}"
