# 분류 방식 비교 실험 (ml_eval)

현재 규칙 엔진과 새 방식(유사사례 검색, 로컬 LLM)을 **같은 정답셋**으로 비교하는 오프라인 실험 도구입니다.
프로그램 동작에는 영향을 주지 않습니다. 결과는 특정 정답셋 기준 진단치이며, 정답셋이 바뀌면 수치도 바뀝니다.

## 데이터 보호

- 작업 폴더는 `ML_EVAL_DIR`(기본 `ml_eval_work/`)이며 `.gitignore`로 저장소에서 제외합니다.
- MES 원본, 정답셋, 모델 출력은 모두 이 폴더에만 저장합니다. 원문에는 작업자 이름이 들어 있으므로 커밋하지 마세요.
- 모든 모델은 로컬(CPU)에서 실행하며 고장 기록을 외부로 보내지 않습니다. 모델 파일만 내려받습니다.

## 준비

```
pip install -r requirements.txt scikit-learn fastembed llama-cpp-python huggingface_hub
```

`ML_EVAL_DIR/data/y2024.xlsx`, `y2025.xlsx`, `y2026.xlsx`에 MES 비가동 내보내기를 둡니다.
모델은 `ML_EVAL_DIR/models/`에 둡니다.
- 임베딩: fastembed가 `models/fe`에 자동으로 받습니다(`intfloat/multilingual-e5-large` 등).
- LLM GGUF: `unsloth/gemma-4-E4B-it-GGUF`의 `gemma-4-E4B-it-Q4_K_M.gguf`, `Qwen/Qwen3-4B-GGUF`의 `Qwen3-4B-Q4_K_M.gguf`.

## 순서

1. `python tools/ml_eval/baseline.py`: 현재 규칙 엔진으로 전체 기록을 분류합니다(`exp/baseline.pkl`).
2. `python tools/ml_eval/make_sample.py`: 상태별 층화 표본(기본 300건)과 라벨링용 텍스트를 만듭니다.
3. 사람이 `exp/gold_labels_*.txt`에 정답 부품군을 적습니다. 형식은 `번호 코드[,코드] [?]`이고 `?`는 해석이 갈리는 건입니다. 코드는 `gold_build.py`의 `CODES`를 따릅니다.
4. `python tools/ml_eval/gold_build.py`
5. `python tools/ml_eval/retrieval.py tfidf` 또는 `python tools/ml_eval/retrieval.py e5large intfloat/multilingual-e5-large`
6. `python tools/ml_eval/llm.py <gguf 파일명> <태그> all`: 태그는 `gemma4e4b` 또는 `qwen3_4b`입니다.
7. `python tools/ml_eval/compare.py`: 방식별 자동처리율, 자동건 정확도, 놓친 오류율을 비교합니다.
8. `python tools/ml_eval/export_review.py`: 정답셋 검수용 엑셀을 만듭니다.

## 평가 기준

- 정답은 "이번 정지에서 실제로 고장 나거나 수리·교체·조정된 부품군"(카탈로그 중간 그룹 59개 + `없음`)입니다.
- **자동처리율**: 사람 검토 없이 확정되는 비율입니다.
- **자동건 정확도**: 자동 확정된 건 중 정답 주부품이 포함된 비율입니다.
- **놓친 오류율**: 전체 기록 중 자동 확정됐지만 틀린 비율입니다. 아무도 모르게 보고서에 들어가는 오류입니다.
- 층화 표본은 3년 전체의 상태별 건수로 가중해 전체 모집단 기준으로 환산합니다.
