"""纯文本后处理逻辑，可独立于 ASR 依赖进行测试。"""

import re
from typing import Dict, Iterable


def filter_filler_words(text: str, filler_words: Iterable[str]) -> str:
    """过滤口语词并清理残留空格与标点。"""
    if not filler_words:
        return text

    for filler in filler_words:
        text = text.replace(filler, "")

    text = re.sub(r" +", " ", text)
    text = re.sub(r"\s+([，。！？、；：,.!?;:])", r"\1", text)
    text = re.sub(r"([，。！？、；：])(\s+)", r"\1", text)
    text = re.sub(r"([。！？])\s*，", r"\1", text)
    text = re.sub(r"([，。！？、；：])\1+", r"\1", text)
    text = re.sub(r"^[，。、；：]+", "", text)
    return text.strip()


def correct_vocabulary(text: str, vocabulary_corrections: Dict[str, str]) -> str:
    """按不区分大小写规则替换易错词。"""
    if not vocabulary_corrections:
        return text

    for wrong, correct in vocabulary_corrections.items():
        text = re.sub(re.escape(wrong), correct, text, flags=re.IGNORECASE)
    return text
