# Local PDF storage

개발 중 사용 권한이 있는 실제 증권사 리포트와 DART PDF만 이 디렉터리에 둘 수 있다. PDF 원본은 저작권과 저장소 용량 문제로 Git에 커밋하지 않는다. Docker 환경에서는 named volume의 `/data/raw`가 사용되며 이 디렉터리는 직접 마운트되지 않는다.

