"""Conservative, sector-independent economic facts and extractive card validation.

Offsets always refer to the untouched PDF page text. Matching normalization is
never used to rewrite a citation, calculate values, or infer missing comparisons.
"""
import re
from dataclasses import asdict, dataclass

from .citation_display import normalize_display_quote

# Economic measures, not company/product dictionaries. A cost increase has the
# opposite sign to a sales increase. Investment/supply changes need explicit risk.
BENEFIT = ("영업이익률", "영업이익", "순이익", "매출액", "매출", "수익성", "마진", "판매량",
    "판매대수", "판매", "출하량", "수주잔고", "수주", "수요", "생산성", "점유율", "가동률", "현금흐름", "이익", "보험손익", "투자손익", "OP", "ASP", "평균판매가격", "판매가격")
BURDEN = ("재고평가손실", "평가손실", "충당금", "손해율", "손실", "적자", "원가", "비용", "법인세부담", "법인세 부담", "부채 부담", "부채", "재고")
CONTEXTUAL = ("공급", "투자", "가격", "Capex")
METRIC = re.compile("|".join(re.escape(word) + (r"(?![A-Za-z])" if word.isascii() else "") for word in sorted(BENEFIT + BURDEN + CONTEXTUAL, key=len, reverse=True)), re.I)
CHANGE = re.compile(r"상회|하회|증가|감소|급상승|상승|하락|확대|축소|개선|악화|둔화|부진|저조|증대|회복|급증|급감|급등|급락|성장|인상|인하(?![여한고])|상향|하향|부담|병목|적자|손실")
UP = {"상회", "증가", "급상승", "상승", "확대", "개선", "증대", "회복", "급증", "급등", "성장", "인상", "상향"}
DOWN = {"하회", "감소", "하락", "축소", "악화", "둔화", "부진", "저조", "급감", "급락", "인하", "하향"}
UNSAFE = re.compile(r"매수|매도|목표주가|저평가|매력|투자\s*기회|주가\s*(?:상승|하락|전망|충격)|수익\s*보장")
GENERIC = re.compile(r"^(?:(?:긍정|부정|주의|위험)\s*요인[:：]?\s*)|^(?:실적\s*개선\s*(?:기대|전망)|수요\s*관련\s*전망)$")


@dataclass(frozen=True)
class EconomicFact:
    subject: str
    metric: str
    metric_type: str
    direction: str
    comparison: str | None
    polarity: str
    source_phrase: str
    certainty: str


def matching_text(value: str) -> str:
    # Handle extraction wrapping only; raw source and page offsets stay separate.
    return re.sub(r"\s+", " ", normalize_display_quote(value)).strip()


def economic_facts(quote: str) -> list[dict]:
    value = matching_text(quote)
    facts = []
    # Clause boundaries prevent a revenue increase from borrowing the later cost
    # increase or the opposite direction in the next clause.
    for clause in re.split(r"[;。]|(?<=[.!?])\s+|(?:했지만|하지만|반면|그러나)|(?<=으며)[, ]+|(?<=하고)[, ]+", value):
        metrics = list(METRIC.finditer(clause))
        for index, metric in enumerate(metrics):
            name = metric.group()
            end = metrics[index + 1].start() if index + 1 < len(metrics) else len(clause)
            tail = clause[metric.end():end]
            changes = list(CHANGE.finditer(tail))
            if name in {"적자", "손실"} and not changes and re.search(r"상태|지속|이어|발생", tail):
                facts.append(asdict(EconomicFact("", name, "burden", "지속" if re.search(r"상태|지속|이어", tail) else "발생",
                    None, "negative", clause[metric.start():].strip(), "reported")))
                continue
            if not changes:
                continue
            change = changes[0]
            direction = change.group()
            # The direction must modify this measure, not a later business,
            # discount or cost hidden in the same sentence. Remove only explicit
            # grammatical/measurement bridges; unknown intervening nouns fail closed.
            bridge = tail[:change.start()]
            bridge = re.sub(r"\([^)]*\)", "", bridge)
            bridge = re.sub(r"시장\s*(?:기대치?|예상치)|컨센서스|기대치|추정치|전망치|전년동기|전년|전분기|전기|대비|동기|가파르게|크게|소폭|지속적|점진적|전반적|추가|다소|대폭|일시적|약|수준|조원|억원|백만원|원|YoY|QoQ", "", bridge, flags=re.I)
            bridge = re.sub(r"으로|에서|보다|은|는|이|가|도|를|을|의|로", "", bridge)
            if re.search(r"[가-힣A-Za-z]", bridge):
                continue
            suffix = tail[change.end():]
            # An object ("성장을 견인") describes an effect, not a change of
            # the preceding measure ("수주 성장"). Do not invent that relation.
            if re.match(r"\s*(?:을|를)\s*(?:견인|이끌|주도|촉진|뒷받침)", suffix):
                continue
            # Negated, hypothetical or contradicted directions are not facts.
            if re.search(r"^.{0,25}(?:않|아니|미미|어렵|없|경우|다면)", suffix):
                continue
            metric_type = "benefit" if name in BENEFIT else "burden" if name in BURDEN else "contextual"
            polarity = "ambiguous"
            if metric_type in ("benefit", "burden"):
                if direction in UP | DOWN:
                    # Improvement/recovery always improve the metric's economics;
                    # numerical increases/decreases invert for burden metrics.
                    positive = direction in UP
                    if metric_type == "burden" and direction not in {"개선", "회복", "악화"}:
                        positive = not positive
                    polarity = "positive" if positive else "negative"
                elif direction in {"적자", "손실", "부담"}:
                    polarity = "negative"
            else:
                if re.search(r"위험|우려|부담|저항|차질", clause):
                    polarity = "negative"
                elif name.casefold() in {"가격", "asp"}:
                    # Price can be a cost or revenue driver; require its role or
                    # an explicit profitability link instead of guessing a sign.
                    if re.search(r"판매|제품|판가|이익|수익성", clause):
                        polarity = "positive" if direction in UP else "negative" if direction in DOWN else "ambiguous"
                    elif re.search(r"원재료|매입|원가", clause):
                        polarity = "negative" if direction in UP else "positive" if direction in DOWN else "ambiguous"
            comparison_context = clause[:metric.end()+change.end()]
            comparison_match = re.search(r"시장\s*(?:기대치?|예상치)|컨센서스|기대치|기존\s*추정치", comparison_context, re.I)
            if (comparison_match and comparison_match.start() < metric.start()
                    and not any(prior.group() == name for prior in metrics[:index])):
                # A metric appearing only inside the benchmark's parentheses is
                # not proof of what the company reported (possibly clipped OCR).
                continue
            if comparison_match is None and direction not in {"상회", "하회"}:
                comparison_match = re.search(r"전년\s*대비|전분기\s*대비|YoY|QoQ", comparison_context, re.I)
            if direction in {"상회", "하회"} and not comparison_match:
                # A benchmark is mandatory; merely exceeding a number is not a
                # market-expectation fact.
                comparison = None
                polarity = "ambiguous"
            else:
                comparison = comparison_match.group() if comparison_match else None
            prefix = clause[:metric.start()].strip(" ,:-•")
            subject_match = re.search(r"([가-힣A-Za-z0-9/·]+(?:\s+[가-힣A-Za-z0-9/·]+){0,2})\s*(?:의|부문)?\s*$", prefix)
            subject = subject_match.group().strip() if subject_match else ""
            if re.search(r"기대|컨센서스|\d|[은는을를]$|관련|따라|속에|통해|향후|중후반|병목은|큼|연결되는", subject):
                subject = ""
            phrase = clause[metric.start():metric.end() + change.end()].strip()
            # "시장 기대를 상회했다" describes a reported result. A benchmark
            # containing 기대/예상 is not itself a forecast qualifier.
            certainty_context = re.sub(r"시장\s*(?:기대치?|예상치)|컨센서스|기대치|기존\s*추정치", "", suffix)
            certainty = "forecast" if re.search(r"전망|예상|추정|기대|가능성", certainty_context) else "reported"
            facts.append(asdict(EconomicFact(subject, name, metric_type, direction, comparison,
                polarity, phrase, certainty)))
    return facts


def fact_title(fact: dict) -> str | None:
    if fact["polarity"] not in {"positive", "negative"}:
        return None
    # Only copy labels present in the fact; no company name is supplied from metadata.
    subject = re.sub(r'^(?:으로|등으로|로)\s+', '', fact['subject'])
    title = " ".join(part for part in (subject, fact["metric"], fact["comparison"], fact["direction"]) if part)
    if fact["certainty"] == "forecast":
        title += " 전망"
    return title if len(title) <= 120 and not UNSAFE.search(title) and not GENERIC.search(title) else None


def grounded_card(candidate: dict, perspective: str) -> tuple[str, str] | None:
    if candidate.get("quality_status") != "valid" or candidate.get("analysis_perspective") != perspective:
        return None
    if not (isinstance(candidate.get("char_start"), int) and isinstance(candidate.get("char_end"), int)
            and candidate["char_end"] > candidate["char_start"] and candidate.get("page_number", 0) >= 1):
        return None
    if candidate.get("span_kind") == "table" and not candidate.get("table_verified"):
        return None
    for fact in candidate.get("facts", []):
        if fact["polarity"] != perspective:
            continue
        title = fact_title(fact)
        if title:
            return title, f"보고서는 ‘{title}’ 내용을 제시합니다."
    return None


def supported_claim(title: str, reason: str, candidates: list[dict]) -> bool:
    """Fail closed on new names, numbers, direction, causal or comparison claims.

    Paraphrases outside this extractive vocabulary are lowered to a grounded card,
    not treated as semantically equivalent without evidence.
    """
    if UNSAFE.search(title + " " + reason) or GENERIC.search(title):
        return False
    facts = [fact for candidate in candidates for fact in candidate.get("facts", [])]
    if not any(fact["metric"] in title and fact["direction"] in title for fact in facts):
        return False
    source = re.sub(r"\s+", "", matching_text(" ".join(candidate["quote"] for candidate in candidates))).casefold()
    for token in re.findall(r"[A-Za-z가-힣0-9]+(?:[.,]\d+)?", title + " " + reason):
        if token in {"보고서는", "보고서", "내용을", "제시합니다", "언급합니다", "전망", "전망합니다", "기대", "대한", "관련"}:
            continue
        token = re.sub(r"(?:에서는|으로|에서|에는|이며|은|는|이|가|을|를|의)$", "", token)
        if token.casefold() not in source:
            return False
    return True
