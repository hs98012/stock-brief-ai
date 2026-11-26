# Fact fusion Implementation Plan

**Goal:** 신규 PDF의 독립 추출 경로에서 검증된 근거를 병합하고 shadow retrieval로 측정한다.
**Architecture:** 좌표 문단/native cell/OCR region을 별도 후보로 만든다. 원문 연결 검증 후 구조화 text/offset으로 직렬화한다. 신규 version 전용 검색 후보 승격을 사용한다.
**Tech Stack:** PyMuPDF, Tesseract, SQLAlchemy, bge-m3, BM25/RRF.
**Spec:** docs/superpowers/specs/2026-09-23-fact-fusion.md

## Constraints / review focus
- 사용자 변경과 활성·이전 shadow 데이터 보존. 기업/정답 기반 분기 금지.
- 열 섞임, native/OCR 충돌, 손상 기간, 낮은 confidence, 청크 밖 헤더를 fixture로 검증.
- 기존 API/원문 offset 계약 유지. confidence는 정답 보증이 아니다.

## Tasks
- [x] `test_fact_fusion.py`: 좌표 열 순서, native 정상 후보 보존, 충돌 보류, native cell provenance, 낮은 confidence 거절의 실패 테스트 실행.
- [x] `fact_fusion.py`, `native_tables.py`: 문단 XY 분리, find_tables cell 검증, 출처별 fact 병합, 직렬화 구현. `pdf_pipeline.py`에서 누락 영역 OCR 연결.
- [x] `chunking.py`, `service.py`, `shadow_revision.py`: 검증된 문단/표 span별 청크; 이전 버전은 기존 split 유지.
- [x] `extraction_provenance.py`, `search.py`: 신규 version numeric/table 검증 및 후보 승격. 기존 활성 출력 동일 확인.
- [ ] 관련 backend 테스트 후 새 shadow 파싱·임베딩 및 원문 대조. 원시 JSON은 ignored 결과 디렉터리에만 저장.
- [ ] 계약 문서와 audit에 실제 결과 기록. check.sh, diff-check, compose build, health 검증.

사용자가 현재 작업 트리에서 진행을 승인했으므로 동일 작업 트리에서 직접 수행하고 커밋하지 않는다.
