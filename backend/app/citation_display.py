import re
from dataclasses import dataclass
from typing import Any


_NOISE_LINE = re.compile(r"^\s*(?:be|eens)\s*$", re.IGNORECASE)
_HANGUL_AT_END = re.compile(r"([가-힣]+)$")
_HANGUL_AT_START = re.compile(r"^([가-힣]+)")
_POSTPOSITIONS = {"은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "로", "으로",
    "에서", "에게", "부터", "까지", "보다", "처럼", "만", "뿐"}
_TABLE_METRICS = ("매출액", "영업이익률", "영업이익", "EBITDA", "Capex", "QoQ/YoY")
_TABLE_ROWS = ("Foundry/LS", "DRAM", "NAND")


@dataclass(frozen=True)
class CitationDisplay:
    kind: str
    display_quote: str | None
    table_labels: list[str]
    note: str | None
    table_facts: dict[str, Any] | None = None


def normalize_display_quote(raw: str) -> str:
    """Normalize display-only OCR line wrapping while preserving the stored quote."""
    lines = [line.strip() for line in raw.splitlines() if line.strip() and not _NOISE_LINE.fullmatch(line)]
    if not lines:
        return ""
    rendered = lines[0]
    for line in lines[1:]:
        left = _HANGUL_AT_END.search(rendered)
        right = _HANGUL_AT_START.search(line)
        join_word = False
        if left and right:
            left_word, right_word = left.group(1), right.group(1)
            join_word = len(left_word) == 1 or len(right_word) == 1 or right_word in _POSTPOSITIONS
        rendered += ("" if join_word else " ") + line
    return re.sub(r"[ \t]+", " ", rendered).strip()


def _is_table_fragment(raw: str) -> bool:
    numeric_tokens = re.findall(r"(?<![A-Za-z가-힣])[-+]?\d[\d,.]*(?:%|배)?", raw)
    labels = sum(label.casefold() in raw.casefold() for label in _TABLE_METRICS + _TABLE_ROWS)
    return len(numeric_tokens) >= 8 and labels >= 2


def _exact_table_labels(raw: str) -> list[str]:
    labels: list[str] = []
    title = re.search(r"표\s*\d+\s*[.]?\s*[^\n\r]{1,40}", raw)
    if title:
        labels.append(title.group(0).strip())
    unit = re.search(r"\(\s*조원\s*,\s*%\s*\)", raw)
    if unit:
        labels.append(unit.group(0))
    periods = list(dict.fromkeys(re.findall(r"\b(?:[1-4]Q\d{2}F?|20\d{2}F?)\b", raw)))
    labels.extend(periods[:8])
    labels.extend(label for label in _TABLE_METRICS + _TABLE_ROWS if label.casefold() in raw.casefold())
    return list(dict.fromkeys(labels))


def _numbers(line: str) -> list[str]:
    return re.findall(r"(?<![A-Za-z가-힣])[-+]?\d+(?:[.,]\d+)?", line)


def _row_label(line: str) -> str | None:
    first_number = re.search(r"(?<![A-Za-z가-힣])[-+]?\d", line)
    if not first_number:
        return None
    label = line[:first_number.start()].strip(" |:")
    return label if label and re.search(r"[A-Za-z가-힣]", label) else None


def _label_matches_hint(label: str, hint: str) -> bool:
    compact_label = re.sub(r"[^a-z가-힣]", "", label.casefold())
    compact_hint = re.sub(r"[^a-z가-힣]", "", hint.casefold())
    if compact_label and compact_label in compact_hint:
        return True
    aliases = {"foundry": "파운드리", "dram": "디램", "nand": "낸드"}
    return any(alias in compact_label and korean in compact_hint for alias, korean in aliases.items())


def extract_table_facts(page_text: str, quote: str, claim_hint: str) -> dict[str, Any] | None:
    """Extract only directly aligned table headers and row values; never infer or calculate."""
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    metric_names = ("영업이익률", "영업이익", "매출액")
    metric = next((name for name in metric_names if re.search(rf"(?m)^\s*{re.escape(name)}\b", quote)), None)
    if metric is None:
        return None
    metric_indexes = [index for index, line in enumerate(lines) if re.match(rf"^{re.escape(metric)}\b", line)]
    for metric_index in metric_indexes:
        title_index = next((index for index in range(metric_index - 1, -1, -1) if re.match(r"^표\s*\d+", lines[index])), None)
        if title_index is None:
            continue
        header_line = next((line for line in lines[title_index + 1:metric_index]
            if len(re.findall(r"\b(?:20\d{2}F?|[1-4]Q\d{2}F?)\b", line)) >= 3), None)
        if header_line is None:
            continue
        annual_periods = re.findall(r"\b20\d{2}F?\b", header_line)
        if len(annual_periods) < 3:
            continue
        unit_match = re.search(r"\(\s*(조원|억원|백만원|십억원)\s*[, ]\s*%\s*\)", lines[title_index])
        if not unit_match:
            continue
        next_boundary = next((index for index in range(metric_index + 1, len(lines))
            if re.match(r"^(?:표\s*\d+|영업이익률|영업이익|매출액|EBITDA|Capex|Q[0Oo][0Qq]/YoY)\b",
                lines[index], re.IGNORECASE)), len(lines))
        rows = []
        for line in lines[metric_index + 1:next_boundary]:
            label = _row_label(line)
            values = _numbers(line)
            if label and len(values) >= len(annual_periods) and label.casefold() in quote.casefold():
                rows.append((label, values))
        matched = [row for row in rows if _label_matches_hint(row[0], claim_hint)]
        if len(matched) != 1:
            continue
        row_label, values = matched[0]
        annual_values = values[-len(annual_periods):]
        if len(annual_values) != len(annual_periods):
            continue
        selected = [(period, value) for period, value in zip(annual_periods, annual_values, strict=True)
            if period in ("2025", "2026F", "2027F")]
        if len(selected) != 3 or any(value not in quote for _, value in selected):
            continue
        title_match = re.match(r"^(표\s*\d+\s*[.]?\s*DS\s+부문\s+실적)\b", lines[title_index], re.IGNORECASE)
        return {"table_title": title_match.group(1) if title_match else None, "metric": metric,
            "row_label": row_label, "unit": unit_match.group(1),
            "values": [{"period": period, "value": value} for period, value in selected],
            "interpretation": f"보고서는 {row_label} 부문의 영업적자가 이어질 것으로 제시합니다."
                if metric == "영업이익" and all(value.startswith("-") for _, value in selected) else None}
    return None


def citation_display(raw: str, page_number: int, page_text: str | None = None,
    claim_hint: str = "") -> CitationDisplay:
    if not _is_table_fragment(raw):
        return CitationDisplay(kind="text", display_quote=normalize_display_quote(raw), table_labels=[], note=None)
    facts = extract_table_facts(page_text or "", raw, claim_hint) if page_text else None
    if facts:
        return CitationDisplay(kind="table", display_quote=None, table_labels=[], note=None, table_facts=facts)
    labels = _exact_table_labels(raw)
    has_title = any(label.startswith("표") for label in labels)
    has_period = any(re.fullmatch(r"(?:[1-4]Q\d{2}F?|20\d{2}F?)", label) for label in labels)
    reliable_labels = labels if has_title and has_period else []
    return CitationDisplay(kind="table", display_quote=None, table_labels=reliable_labels,
        note=f"표 수치는 원문 PDF {page_number}페이지에서 확인할 수 있습니다.")
