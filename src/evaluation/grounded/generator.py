"""Local Ollama question generation for corpus-grounded Silver questions."""

from __future__ import annotations

import json
from typing import Any

import requests


OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
GENERATION_CONFIG = {
    "format": "json",
    "temperature": 0,
    "seed": 1103,
    "num_predict": 1800,
}


class GenerationError(RuntimeError):
    pass


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = text.split("\n", 1)[-1]
        if text.endswith(fence):
            text = text[:-len(fence)]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"model response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GenerationError("model response JSON must be an object")
    return parsed


def ollama_json(model: str, system_prompt: str, user_prompt: str, *, timeout: int = 600) -> dict[str, Any]:
    """Use the explicitly local loopback model only; no remote endpoint fallback."""
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "keep_alive": "15m",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": dict(GENERATION_CONFIG),
    }
    try:
        response = requests.post(OLLAMA_URL, json=body, timeout=timeout)
        response.raise_for_status()
        content = response.json()["message"]["content"]
    except Exception as exc:
        raise GenerationError(f"local Ollama generation failed: {exc}") from exc
    return _parse_json_content(str(content))


def generate_single_evidence(model: str, evidence: dict[str, Any]) -> dict[str, Any]:
    system = (
        "你是繁體中文漁業知識評測題目撰寫器。提供的 Evidence 是唯一資訊來源。"
        "不得使用外部知識、常識補充或推論 Evidence 沒有寫出的數值、魚種、疾病、措施、原因或條件。"
        "只可產生 Evidence 能直接支持的問題與簡短答案。每題必須附上一段從 Evidence 逐字複製的 supporting_quote，"
        "該段必須直接支持答案。不要引用文件名稱、頁碼或編造來源。"
        "只輸出 JSON，結構為 {\"items\":[{\"query_style\":\"direct|paraphrase|contextual\","
        "\"question\":\"...\",\"reference_answer\":\"...\",\"supporting_quote\":\"...\"}]}，"
        "三種 query_style 各一題。direct 保留 Evidence 的核心術語；paraphrase 使用不同說法但不改變事實；"
        "contextual 只改成養殖者提問口吻，不得新增場景條件。引用保留原文數字和單位。"
    )
    user = "Evidence（不得超出此文字）：\n" + str(evidence["text"])
    return ollama_json(model, system, user)


def generate_multidocument(model: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    system = (
        "你是繁體中文漁業知識評測題目撰寫器。以下 Evidence A 與 Evidence B 是唯一資訊來源。"
        "建立三題（direct、paraphrase、contextual），每題都必須同時需要 A 與 B 才能完整回答，"
        "例如整合兩份資料各自明確記載的不同事實；不能只靠其中一份回答。不得補入外部知識、額外數值、魚種、疾病或條件。"
        "問題和答案不可出現 Evidence A、Evidence B 或來源標籤字樣。答案必須分別包含 A、B 的一項可直接支持內容。"
        "每份 Evidence 的 supporting_quote 必須是從該 Evidence 連續逐字複製的原文，不可改字、摘要或補標點。"
        "只輸出 JSON：{\"items\":[{\"query_style\":\"direct|paraphrase|contextual\",\"question\":\"...\","
        "\"reference_answer\":\"...\",\"supporting_quotes\":[{\"evidence\":\"A\",\"quote\":\"...\"},"
        "{\"evidence\":\"B\",\"quote\":\"...\"}]}]}。"
        "contextual 只改變提問語氣，不得增加資料中不存在的現場條件。"
    )
    user = "Evidence A：\n" + str(left["text"]) + "\n\nEvidence B：\n" + str(right["text"])
    return ollama_json(model, system, user)


def generate_calculation_questions(model: str, evidence: dict[str, Any], low: float,
                                   high: float, biomass_values: list[int]) -> dict[str, Any]:
    scenarios = [
        {"biomass_kg": value, "query_style": style}
        for value, style in zip(biomass_values, ("direct", "paraphrase", "contextual"))
    ]
    system = (
        "你只負責用繁體中文為指定的確定性計算情境改寫自然語言問題，不負責計算答案。"
        "Evidence 是計算比例的唯一來源。不得更改 Evidence 中的比例或指定的 biomass_kg；不得補入其他條件。"
        "每個情境輸出一個 question，保留 query_style 和 biomass_kg。只輸出 JSON："
        "{\"items\":[{\"biomass_kg\":100,\"query_style\":\"direct\",\"question\":\"...\"}]}。"
    )
    user = (
        f"Evidence：\n{evidence['text']}\n\n"
        f"明確比例：魚體重量的 {low:g}% 至 {high:g}%。\n"
        f"請對下列固定輸入各寫一題：{json.dumps(scenarios, ensure_ascii=False)}"
    )
    return ollama_json(model, system, user)
