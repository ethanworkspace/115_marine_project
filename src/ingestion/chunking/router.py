"""Choose a structure-aware strategy from verified metadata and page structure."""

from __future__ import annotations

import re
from typing import Any

from .base import StrategyDecision


ARTICLE_RE = re.compile(r"第\s*[〇零一二三四五六七八九十百千\d]+\s*條")
HEADING_RE = re.compile(r"(?m)^\s*(?:第.{1,24}[章節]|#{1,6}\s+|[一二三四五六七八九十]+、)")
DISEASE_LABEL_RE = re.compile(r"(?m)^\s*(?:病原|宿主|症狀|診斷|防治|治療|預防)\s*[:：]?")


def choose_strategy(document: dict[str, Any], pages: list[dict[str, Any]]) -> StrategyDecision:
    title = str(document.get("title") or "")
    doc_type = str(document.get("document_type") or "")
    topics = document.get("topics") or []
    if isinstance(topics, str):
        topics = [topics]
    metadata_words = " ".join([title, doc_type, *(str(x) for x in topics)]).casefold()
    body = "\n".join(str(p.get("selected_text") or p.get("text") or "") for p in pages)
    article_count = len(ARTICLE_RE.findall(body))
    headings = len(HEADING_RE.findall(body))
    disease_labels = len(DISEASE_LABEL_RE.findall(body))

    legal_markers = ("法規", "法令", "辦法", "規則", "條例", "法律", "law", "regulation", "statute")
    if any(term.casefold() in metadata_words for term in legal_markers) and article_count:
        return StrategyDecision("regulation", evidence=("legal title/type/topic", f"article_markers={article_count}"))
    if any(term in metadata_words for term in ("疾病", "病害", "病原", "disease", "health")) and (disease_labels or "病" in title):
        return StrategyDecision("disease", evidence=("disease title/type/topic", f"disease_labels={disease_labels}"))
    manual_markers = ("手冊", "指南", "養殖要點", "技術指引", "manual", "handbook", "guide", "sop")
    if any(term.casefold() in metadata_words for term in manual_markers) and headings:
        return StrategyDecision("manual", evidence=("manual title/type/topic", f"heading_markers={headings}"))
    if article_count >= 2 and any(term in body for term in ("法規", "本法", "條文", "主管機關")):
        return StrategyDecision("regulation", evidence=(f"article_markers={article_count}", "legal body markers"))
    if (disease_labels >= 2 or "病" in title) and any(term in body for term in ("病原", "症狀", "診斷", "防治")):
        return StrategyDecision("disease", evidence=(f"disease_labels={disease_labels}", "explicit disease headings"))
    if headings >= 2:
        return StrategyDecision("manual", warning="metadata did not identify document type; heading structure selected manual strategy", evidence=(f"heading_markers={headings}",))
    return StrategyDecision("fallback", warning="document type or stable heading structure could not be confirmed", evidence=(f"article_markers={article_count}", f"heading_markers={headings}"))
