# etl/mask.py
# 职责：文本脱敏——手机号/邮箱/微信号统一替换为 [CONTACT]
# 依赖：re
# 说明：纯函数，不保存原值，不落日志

from __future__ import annotations

import re

# 手机号：1开头11位
_PHONE = re.compile(r"1[3-9]\d{9}")
# 邮箱
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 微信号：字母开头6-20位或微信相关描述
_WECHAT = re.compile(r"(?:微信|微信号|wx|WeChat|wechat)[:：\s]*[a-zA-Z0-9_-]{6,20}")
# QQ号
_QQ = re.compile(r"(?:QQ|qq)[:：\s]*\d{5,12}")
# 固话：区号-号码
_LANDLINE = re.compile(r"0\d{2,3}-?\d{7,8}")

_PLACEHOLDER = "[CONTACT]"


def mask_text(text: str) -> str:
    """对文本进行脱敏：手机号/邮箱/微信号/QQ/固话统一替换为 [CONTACT]。"""
    if not text or not isinstance(text, str):
        return text
    result = text
    for pat in (_PHONE, _EMAIL, _WECHAT, _QQ, _LANDLINE):
        result = pat.sub(_PLACEHOLDER, result)
    return result


def mask_column(series: "pd.Series") -> "pd.Series":  # type: ignore[name-defined]
    """对 pandas Series 整列脱敏。"""
    return series.apply(mask_text)
