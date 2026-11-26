# Persistent RAG E2E 복원 — 2026-10-12

이번 작업은 OCR·embedding 생성·retrieval query·LLM 분석을 실행하지 않았다. 기존 extraction을 검증하고 E2E DB에 복원했다. 전체 regression의 synthetic/mock 테스트는 실행했다.

1. **변경 파일**: `scripts/e2e-persistent-compose.yml`, `scripts/restore_e2e_persistent.py`, `.gitignore`, `.env.example`, 이 보고서. 로컬 `.env`에는 E2E 전용 비밀번호만 추가했다(값 미공개). `.e2e-persistent/`는 Git에서 제외한다. 기존 production source/API/schema/검색 설정은 수정하지 않았다. 기존 미커밋 변경은 보존했다.

2. **Persistent E2E DB**: image `pgvector/pgvector:pg16`; container `stock-brief-e2e-persistent-pg`; DB/user `stock_brief_e2e_restore`; host `127.0.0.1:55433`; external volume `stock_brief_e2e_persistent_pgdata`; `PGDATA=/var/lib/postgresql/data/pgdata`; restart `unless-stopped`. Root `.env`의 `E2E_PERSISTENT_DB_PASSWORD`만 별도로 사용한다. 복원 도구는 target host/port/DB/user를 고정하고 DB identity를 검증한다. 임의 `DATABASE_URL`을 복원 대상으로 사용하지 않는다.

3. **Production 격리 증거**: production container `stock-brief-ai-postgres-1`, port 설정 5432, volume `stock-brief-ai_postgres_data`와 이름·포트·DB/user·volume·Compose project/network가 다르다. Production Compose와 container state/mount가 전후 동일하다. Production은 계속 exited 상태이며 DB 접속·복사·migration·재시작을 하지 않았다. 현재 production table hash는 접근 금지 때문에 **확인할 수 없습니다**. 상태/mount 조회를 데이터 무결성 검증으로 대체하지 않는다. `production-container-before.txt`, `production-container-after.txt`, `recreate-integrity.json` 참조.

4. **Tmpfs 미사용**: Docker inspect의 `HostConfig.Tmpfs=null`, mount type `volume`, mount name `stock_brief_e2e_persistent_pgdata`, destination `/var/lib/postgresql/data`. 실제 PGDATA가 이 mount 하위에 있다. `external: true`이므로 Compose 수명주기와 volume 수명주기가 분리된다. E2E 컨테이너 force-recreate 후에도 같은 volume과 DB snapshot을 확인했다. `down -v` 및 volume 삭제 명령은 실행하지 않았다. `persistent-volume-check.json`, `mounts.json`, `mounts-after-recreate.json`, `volume.json` 참조.

5. **PDF 및 extraction hash**: PDF SHA-256 `3489541bb393c16772ba3ed5d31c3f34a035ba36a472eabc884fa6ad60209808`. 과거 PDF hash와 복사본 bytes 일치, PDF physical page count 9와 page size 일치. 9개 raw extraction/file hash와 final_text hash는 `restoration-audit.json`에 각각 기록했다. 그 9개 hash 목록의 aggregate SHA-256 `a81997f619e4dc035b0e78e9df3aabadf7aa6ad8e897d10b9288bf08b15d2504`. 정렬된 JSON hash 목록을 해시한 값이며 원본 PDF hash와 구분한다.

6. **복원 페이지**: Document 1개, Pages 9개, PageExtraction 9개. native_text, ocr_text, final_text, text_source, ocr_error, parser_version, source hash, provenance JSON, table_facts JSON을 보존하고 DB에서 원본 artifact와 다시 대조했다. PageExtraction 내 native/OCR/Paddle source·table cell topology·좌표·span 정보를 그대로 저장했다. OCR은 재실행하지 않았다.

7. **복원 chunk**: 583개 원래 UUID를 유지했고 전역 ID 유일성, document/page mapping, 원문 content와 char offset 범위/substring, admission 결과의 범위 roundtrip을 확인했다. Page별 chunk count는 아래와 같다. schema에는 searchable 컬럼이 없어 현재 `fused_index.searchable` 계산값을 sidecar에 기록했다. Searchable anchor 134개, non-searchable dependency/source chunk 449개로 구성되며 모두 embedding 재생성 대상이다. 검색 query/ranking/RRF는 실행하거나 변경하지 않았다.

| Page | Chunk | Verified facts | final_text SHA-256 |
|---|---:|---:|---|

| 1 | 60 | 35 | `bc81ce1f1fc796f6f4085606c12e03759db70523d96a2062edf6e81d539cab71` |

| 2 | 39 | 0 | `6aeafa04bf749417dd8928479b116dea6a73ae7e80ee151b1a2beddf2e72856c` |

| 3 | 4 | 0 | `da9174b12d5a094b744448d1e8f4d7a8f6896e288eec7769b7bbc938f8d3c1d1` |

| 4 | 37 | 0 | `7d483f56e3808ff836fdd28113540d1338bdd871b3915cc763f76d1125c20d26` |

| 5 | 4 | 0 | `ba29b917a5dce7960acf5981de47bfaf67407a8ba5ab786e9724c28c1ee0291c` |

| 6 | 2 | 0 | `21f6d33d0969c418191c875b0a3a6cf876edbba588805d682ff9077ab33546b2` |

| 7 | 432 | 276 | `cd2943b4d65284753ca6c31dcdd4f81dc8fc682c7009d14d4444656ab5f4ee3e` |

| 8 | 0 | 0 | `2e3a74dd61f723e9750fd00de91f87ea7fedb71bfd70fe36358466bfb000ac1e` |

| 9 | 5 | 0 | `8b254d1d2cc94693b147b7e2a6dcc998488c696835b2a1302cfab724483c47d4` |

8. **Source/span/provenance 검증**: fact→chunk source link 1,552개, literal quote span 35,218개, 유효 coordinate bbox 43,986개 검증. 이 수는 중첩 provenance/dependency 내 반복을 포함한 검사 횟수다. 기존 verified facts 311개(1p 35, 7p 276)가 현재 offline validator 결과와 전체 JSON 일치했다. Selected words의 char slice와 text도 확인했다. Authoritative table_facts/dependency_groups를 검사하며 rejected observation을 유효 evidence로 승격하지 않았다. 원본 좌표계는 unrotated PDF points/physical page index + 1이다. Dependency group ownership_id/context_id는 원본에서 모두 NULL이며 그대로 보존했다. Non-E2E identity와 변조된 extraction hash/source span을 거부하는 음성 테스트도 통과했다.

9. **미복원/누락 metadata**: 원래 Page UUID, page_image_path, chunk.section_title은 page dump에 없다. Page UUID는 document UUID+physical page number를 사용한 명시적 새 복원 uuid5이며 `restoration-audit.json`에 mapping을 기록했다. page_image_path와 section_title은 NULL이다. 따라서 원래 모든 DB row와 완전히 동일하다고 주장하지 않는다. Fact provenance에 없는 ownership/context ID는 만들지 않았다. Embedding vector, 이전 analysis_runs, 최종 LLM output, evidence DB PK/answer_item ID는 유실 또는 부재 상태이며 재구성하지 않았다.

10. **Embedding 재생성 준비**: 전부 NULL 583개, Document embedding_status `not_started`, provider `ollama`, model `bge-m3`, dimensions 1024. Vector 유실/미생성을 error/reason에 명시했다. `embedding-targets.json`에 ID/content hash/offset을 기록했고, `embedding-inputs.jsonl`에 기존 production 함수 `fused_index.retrieval_text`로 만든 583개 실제 입력 문자열·SHA-256·searchable flag·source mapping을 보존했다. 문자열 준비만 했으며 모델/검색 호출은 없다. 입력 파일 SHA-256 `add6d939e1049c2fc6b00ff9b2143375a9adff1cede370b6460a7d418fa40068`. Embedding 함수는 이 583개 NULL vector를 대상으로 batch 생성 후 성공한 vector를 commit하는 기존 경로를 그대로 사용할 수 있다. 로컬 Ollama availability/model runtime은 이번 작업에서 호출하지 않아 **확인할 수 없습니다**.

11. **DB restart/recreate 전후**: 아래 모든 count/hash가 restart 전·restart 후·force-recreate 후 일치한다. DB snapshot은 모든 column을 canonical JSON으로 변환하고 row를 정렬한 뒤 SHA-256을 계산했다. `db-before-restart.json`, `db-after-restart.json`, `db-after-recreate.json`, `restart-integrity.json`, `recreate-integrity.json` 참조.

| Table | Count 전/후/재생성 | SHA-256 (모두 동일) |
|---|---:|---|

| documents | 1/1/1 | `15bb7a0945e38620a6d85b2b9f6969116c43bf8657a1736f08c160cad92459c5` |

| pages | 9/9/9 | `71521a6bd0193a653faa2bacc6714e5650cdaec1e0720e48774435c4fc27b412` |

| page_extractions | 9/9/9 | `d7a3fe459faf3924d0c372301b42fe51c0ec4d0b42f1f7f60e15c1134b057aff` |

| chunks | 583/583/583 | `de996bb621419bade57a04692ffcd9be5cb3eaebd660b2511e5ef29ebcd13c64` |

| analysis_runs | 0/0/0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

| shadow_revisions | 0/0/0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

| shadow_pages | 0/0/0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

| shadow_chunks | 0/0/0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

| alembic_version | 1/1/1 | `8d5b84bc2c3f807c53c91795ee97aa8fc0d5fa881f320aa65985230dac878a70` |

Vector non-NULL count 0, embedding column type `vector(1024)`. E2E backup `restored-e2e.dump`와 `schema.sql`을 영구 로컬 경로에 저장했고 `pg_restore --list`로 dump 형식을 확인했다. 실제 호스트 재부팅은 수행하지 않았으며 restart/recreate와 persistent mount를 검증했다. Docker Desktop이 시작되면 restart policy에 따라 컨테이너가 기동할 수 있고 데이터는 volume에 남는다.

12. **기존 artifact 보존**: 원본 일반 파일 2,993개의 path/size/SHA-256/mode/flags를 `files-before.json`, `files-after.json`에 기록했다. 이전 보존 inventory와 일치하고 이번 전후에도 동일하다. 별도 symlink 3개는 `preserved-symlinks.json`에 기록했다. 원본 전체를 저장소의 `.e2e-persistent/preserved/`로 copy2/symlink-preserving 복사해 `/tmp` 정리에 의존하지 않도록 했다. 2,993개 복사본도 원본과 모든 size/hash/mode/flags가 일치한다. Sealed holdout/first-run/gold 및 기존 production code를 포함한 보호 파일 762개도 전후 동일하다. 과거 검색 결과와 analysis_evidence 3개는 historical artifact로만 보존했다. 이전 run을 완료된 것으로 만들지 않았으며 새 분석은 기존 API의 새 AnalysisRun UUID로 수행해야 한다.

13. **전체 regression/compatibility**: `./scripts/check.sh` PASS: backend 648 passed/1 skipped, frontend 7 passed, ESLint PASS, Next production build PASS. 최초 sandbox 실행에서는 macOS nested sandbox 테스트가 실패했으므로 소스 수정 없이 host 권한에서 전체 check를 다시 실행해 통과했다. Alembic 0001→0006 head를 E2E empty DB에만 적용; schema dump와 vector(1024), FK mapping/unique ID/offset SQL 검증 PASS. Offline extraction/chunk audit, negative integrity tests, volume inspection, restart/recreate count/hash, Python compile, git diff --check PASS. 기존 개발 12/12·selected pack 20/20 보고서와 입력/code bytes는 동일하다. 실제 retrieval 금지에 따라 재실행 수치로 주장하지 않고 기존 관측 결과 보존으로 보고한다. `regression-host.log`, `migration.log`, `final-integrity-tests.log`, `negative-integrity-tests.json`, `protected-check.json` 참조.

14. **남은 blocker**: 이 복원 단계의 blocker는 없다. 이후 embedding 생성에는 Ollama 실행 및 bge-m3 model availability 확인이 필요하다. 현재 vector/analysis/LLM output은 없다. 원래 Page UUID 등 누락 metadata는 복구할 수 없으므로 원본 DB와 완전 동일 복원은 **확인할 수 없습니다**. 재부팅 자체를 수행한 검증도 이번 범위에 포함하지 않았다.

15. **다음 실행 명령**: 저장소 root에서 아래 명령으로 환경 재기동·복원 무결성 확인·현재 baseline snapshot·입력 준비를 재실행할 수 있다. DB가 이미 복원된 상태이므로 `restore`를 다시 실행하지 않는다(비어 있지 않으면 거부).

```bash
docker compose --env-file .env -f scripts/e2e-persistent-compose.yml up -d --wait
.venv/bin/python scripts/restore_e2e_persistent.py verify-files
.venv/bin/python scripts/restore_e2e_persistent.py audit
.venv/bin/python scripts/restore_e2e_persistent.py snapshot --snapshot-name recheck-before-embedding.json
.venv/bin/python scripts/restore_e2e_persistent.py prepare-inputs
```

다음 embedding 단계에서만 사용할 명령(이번에는 실행하지 않음). DB target은 같은 고정 guard를 사용하며 OCR/retrieval/LLM을 호출하지 않는다. 성공한 batch는 persistent E2E DB에 commit된다. `snapshot` 명령은 이번 NULL-vector baseline 전용이므로 embedding 이후에는 사용하지 않고 새로운 vector count/hash snapshot을 별도 기록해야 한다.

```bash
.venv/bin/python - <<'PYTHON'
import sys
from uuid import UUID
sys.path.insert(0, 'scripts')
from restore_e2e_persistent import engine, guard
from sqlalchemy.orm import Session
from app.models import Document
from app.embeddings import OllamaEmbeddingProvider
from app.embedding_service import embed_document
provider = OllamaEmbeddingProvider(base_url='http://127.0.0.1:11434', model='bge-m3', dimensions=1024)
with Session(engine()) as db:
    guard(db)
    document = db.get(Document, UUID('5f4001ad-403f-452e-926a-b0ddeb4b60bb'))
    assert document is not None
    result = embed_document(db, document, provider)
    print({'processed': result.processed, 'skipped': result.skipped, 'failed': result.failed})
PYTHON
```

필수 질문 답변:

- **재부팅 후 영속적인가?** 예. tmpfs가 아닌 external named volume에 DB를 저장하고 artifacts/backup은 저장소 영구 경로에 저장했다. 실제 host reboot는 미실행, restart/recreate 후 hash 동일 확인.

- **Production과 완전히 격리됐는가?** DB/container/volume/port/user/network/환경변수 기준으로 격리됐다. Production DB에는 접속하지 않았다. 같은 Docker host를 사용하는 구성이다.

- **OCR 없이 9페이지 복원했는가?** 예. 보존 native/OCR extraction 9개를 사용했다.

- **583개 chunk 근거 연결이 보존됐는가?** 예. 기존 chunk UUID/content/source spans/provenance/fact link를 보존했다. 원래 Page UUID는 없으므로 새 ID mapping을 사용하며 일부 누락 metadata는 NULL이다.

- **Embedding 없이 어디까지 가능한가?** PDF/문서/페이지/추출 metadata 조회, source/좌표/span 검증, 과거 artifact 확인, embedding 입력 준비가 가능하다. 실제 검색은 실행하지 않았다. Vector 검색은 불가능하고 분석 API는 embedding 미완료 상태에서 차단된다.

- **유실 embedding만 재생성할 준비가 됐는가?** 저장 데이터/schema/583개 입력은 준비됐다. 이후 Ollama runtime/model을 확인한 뒤 embedding만 재생성하면 된다. OCR이나 chunk ID 재생성은 필요 없다.
