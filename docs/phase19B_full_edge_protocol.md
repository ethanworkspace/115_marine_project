# Phase 19B — Full Edge RAG protocol

Target、Corpus、Silver、60-question order、300 E4 contexts及models沿用Phase19A immutable inputs。Scope為full RAG，不使用歷史generator-only latency冒充E2E measurement。

## Mandatory gates

1. 核對所有protected checksums、BGE-M3 index/model以及E4 reranker revision/files。
2. Existing `.venv-reranker`必須torch import、CUDA、指定reranker load、single-pair與10-query/500-pair inference全部通過。任何failure即`blocked_reranker_runtime`；不能CPU fallback、更換模型、跳過reranker或自動安裝。
3. 真正重跑60題BM25/Dense/RRF/reranker；Top-5 IDs與order必須60/60符合frozen E4。不能用saved trace當作reproduction。

## Frozen experiments

- R0：retrieval-only。
- F1：E4→Gemma 9B；F2：E4→Qwen Coder 7B。
- BM25 k1=1.5、b=0.75；frozen tokenizer。
- Dense BGE-M3、1024維、Phase12相同artifact/normalization/index。
- BM25/Dense Top50→equal-weight RRF k=60→Top50→E4 reranker→Top5。
- Reranker CUDA float32、batch4、max_length512、原始query+child text。
- Generation generation_v2/schema/Protocolv2.2；temperature0、top_p1、seed15015、output1024、context8192。最多2attempts，只technical failure允許fresh retry一次。
- 不手動調整residency/offload/keep_alive；不做production migration。

## Measurement plan

- Pipeline-cold各3次：相關Ollama models不loaded、reranker不resident、GPUallocation回到可確認baseline；OSfilesystemcache可存在。卸載僅用於定義cold measurement，不能用於偏袒warm模型。
- Warm每condition3×60；Round1 R0/F1/F2、Round2 F2/R0/F1、Round3 F1/F2/R0；題序固定。
- GPU<5%、temperature≤45°C優先，最多等待300秒；未達保存deviation後繼續，不修改Windows policy。
- Monotonic stage timers分開BM25、query embedding、dense search、RRF、reranker、context assembly、generator。
- E2E TTFT：question accepted→first final structured-content token，排除thinking。E2E latency包含retrieval、generation及technical retry。
- 每request在start/after Dense/after reranker/before Generator/after Generator保存residency與memory。未觀測eviction/fallback/spill保持null。
- Process telemetry涵蓋benchmark、Ollama、實際llama-server runners、reranker Python與descendants；分開system/device/process memory，不把shared capacity稱dedicated VRAM。
- IFR分母包含所有formal requests，retry recovery不算final failure；未執行的IFR為null。
- F1/F2三輪完成且無OOM/crash後才各跑1800秒sustained，每300秒分區。
- 不重新跑RAGAS；只比較deterministic behavior preservation。

## Readiness

`phase20_research_integration_ready`需要至少一個非low-priority candidate完成full RAG並建立technical feasibility。
`final_model_selection_ready`另外需要evaluation validity；Independent Judge、人工作業與Qwen unresolved quality不能被性能結果掩蓋。

## This execution

本次在torch import遇到WinError4551，`shm.dll`或相依DLL受到application control policy阻擋。停止全部Retrieval/Generator execution。Gate framework及telemetry已實作；完整runtime runner尚未驗證，不能宣稱full pipeline完成。
