# 동일 36문항·동일 judge 기준 개발 평가

| Metric | Qwen3:8b Closed-book | Petroleum RAG Agent (V22) |
| --- | ---: | ---: |
| Goal Success | 33.3% | 11.1% |
| Claim Coverage | 66.0% | 25.0% |
| Hallucination-free | 58.3% | 83.3% |
| Numerical Accuracy | 68.8% | 18.8% |

| 분야 | Qwen3:8b | Petroleum RAG Agent |
| --- | ---: | ---: |
| Knowledge (knowledge_qa) | 12.5% | 12.5% |
| Reasoning (multi_claim_reasoning) | 0.0% | 0.0% |
| Calculation (direct_calculation + user_formula + kb_formula) | 50.0% | 18.8% |
| Safety (false_premise + unanswerable) | 50.0% | 0.0% |

V22 진단: 계산 실행 8/16, 검증 6/16, 수치 정답 3/16, KB 수식 검색→계산 2/6, KB 수치 정답 0/6, 불필요한 거절 19건, 동일 run 재개 최종 완료 0/4.

관찰된 개발 벤치마크에서 V22는 Qwen보다 hallucination-free 판정 비율이 높았지만, 목표 달성과 수치 정확도는 낮았습니다. 원본 근거 페이지와 식은 KB 수식 문항 5/6에서 찾아졌으나 검색→계산 전환은 2/6에 그쳤습니다. 새 unseen 성능을 입증하는 결과는 아닙니다.

V22는 개발 단계의 동일 36문항 벤치마크에서 평가되었으며, 의미 기반 평가는 동일한 AI judge와 고정된 채점 기준을 적용하였다. 단일 AI 판정자 결과이며 사람의 검토가 아닙니다.
