from src.evaluation.edge.core import MODELS
def row(**kw):
    base=dict(model=MODELS[0],question_id='q',repetition=1,stage='warm',status='answered',
        final_schema_valid=True,first_pass_schema_valid=True,retry_triggered=False,retry_success=False,
        ttft_final_answer_seconds=2.,retry_inclusive_latency_seconds=4.,tokens={'runtime_tps':30.},technical_failures=[])
    return {**base,**kw}
def complete():return [row(question_id=str(q),repetition=r) for r in (1,2,3) for q in range(60)]
def cold():return [dict(independent_cold_start_verified=True) for _ in range(3)]
