from __future__ import annotations

import functools
import os
from pathlib import Path


@functools.lru_cache(maxsize=1)
def get_runtime():
    import torch

    from src.evaluation.reranker_runtime import CrossEncoderRuntime

    root = Path(__file__).resolve().parents[3]
    snapshot = Path(
        os.environ.get(
            "RERANKER_MODEL_PATH",
            str(
                root
                / ".venv-reranker/hf-cache/hub/models--BAAI--bge-reranker-v2-m3/snapshots/"
                "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
            ),
        )
    )
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    return CrossEncoderRuntime(snapshot, device=device, max_length=512, batch_size=4)
