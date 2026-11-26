# 신규 적재 fact-level fusion

사용자 승인 설계: native 좌표 문단, native 표 cells, 누락 영역 OCR 좌표를 독립 추출한다. 후보별 물리 페이지, 원본 bbox, 원문 word span, confidence, source, parser version을 보존한다. 정상 native 후보는 OCR 실패/충돌로 제거하지 않는다. 동일 위치의 모호한 값은 추정하지 않는다.

final_text는 검증된 후보의 직렬화 및 기존 인용 offset 호환 계층이다. 문단·표별 구조화 청크를 생성하고 검증된 table/numeric evidence를 검색에 연결한다. 기존 parser version과 활성 데이터에는 새 규칙을 적용하지 않는다. 새 version shadow만 추가하며 activation 기능은 없다.

평가: 기존 12근거, 활성 7/12 및 이전 shadow 8/12 보존. 실제 bge-m3 임베딩 후 10/12 목표. 숫자만 또는 페이지 일치만으로 채점하지 않는다. 실패를 원본 부재/native 표/OCR/읽기순서/검색으로 분류한다. 생성·UI 변경과 기존 데이터 삭제 금지.
