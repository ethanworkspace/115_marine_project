"""Preserve completed v6 results and verify every archived byte (no inference)."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / 'reports/evaluation/unified_rag_v6_evaluation_20261121_164940'
SELECTION = ROOT / 'reports/evaluation/unified_rag_v6_weighted_selection_20261122_125959'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    now = datetime.now(timezone(timedelta(hours=8), 'Asia/Taipei'))
    out = ROOT / 'reports/closeout' / now.strftime('final_evaluation_%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    metrics = read(EVAL / 'evaluation_metrics_11_source_qc.json')
    record = read(SELECTION / 'result_record.json')
    assert read(EVAL / 'finalization_status.json')['status'] == 'COMPLETE'
    assert metrics['final_n'] == 720
    # Validate the historical inputs that define the final selection.
    historical_checks = []
    for item in read(SELECTION / 'weighted_input_manifest.json') + record['artifacts']:
        path = Path(item['path'])
        actual = digest(path.read_bytes())
        assert actual == item['sha256'], f'Historical hash mismatch: {path}'
        historical_checks.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': actual})

    files = sorted(p for folder in (EVAL, SELECTION) for p in folder.rglob('*') if p.is_file())
    entries = []
    archive = out / 'final_evaluation_evidence.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in files:
            payload = path.read_bytes()
            name = path.relative_to(ROOT).as_posix()
            bundle.writestr(name, payload)
            entries.append({'path': name, 'bytes': len(payload), 'sha256': digest(payload)})
    with ZipFile(archive) as bundle:
        assert len(bundle.namelist()) == len(entries)
        for item in entries:
            payload = bundle.read(item['path'])
            assert len(payload) == item['bytes'] and digest(payload) == item['sha256']
    # Detect source changes during packaging, including additions/removals.
    after = sorted(p for folder in (EVAL, SELECTION) for p in folder.rglob('*') if p.is_file())
    assert after == files, 'Source file inventory changed during archive'
    for path, item in zip(files, entries):
        assert digest(path.read_bytes()) == item['sha256'], f'Source changed: {path}'

    summary = {
        'recorded_at': now.isoformat(), 'status': 'ARCHIVED_AND_BYTE_VERIFIED',
        'purpose': '結案報告使用；截至留存日的最終評估結果',
        'evaluation_run': metrics['run_id'], 'final_inference_count': 720,
        'questions_per_model': 180, 'human_gold_n': metrics['human_gold_n'],
        'report_metric_version': 'evaluation_metrics_11_source_qc.json',
        'original_metrics_retained': 'evaluation_metrics_11.json',
        'model_and_system_layers': metrics['models'],
        'shared_context_precision': metrics['shared_context_precision'],
        'weighted_selection_record': record,
        'archive': archive.name, 'archive_sha256': digest(archive.read_bytes()),
        'archive_files': len(entries), 'archive_bytes': archive.stat().st_size,
        'verification_scope': 'All archive members read back and SHA256 matched; source files rehashed after packaging. Historical selection inputs and recorded artifacts matched. No new inference or protected-corpus audit.',
        'historical_input_checks': historical_checks,
    }
    (out / 'final_results_record.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'evidence_manifest.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [
        '最終評估結果留存／結案報告引用說明',
        f'留存時間：{now.isoformat()}',
        f'來源評測：{metrics["run_id"]}；4 模型 × 180 題，共 720 次最終推論。',
        '報告數值以 evaluation_metrics_11_source_qc.json 的來源QA修正版為準；原始版本及逐筆修正理由均保留。',
        '原始評測報告較前面的準確率表為修正前數值，最末「最終來源QA」為修正版；結案引用以本留存紀錄為準。',
        '原始評測報告中的「不建立加權總分」描述該評測階段；後續70/30加權為另行記錄的探索性選型。',
        '', '加權選型（品質70%／效能30%；總分滿分100）',
    ]
    for row in record['ranking']:
        lines.append(f'{row["rank"]}. {row["model_id"]} {row["model_name"]}：{row["total_out_of_100"]:.2f}（品質 {row["quality_points_out_of_70"]:.2f}／70，效能 {row["performance_points_out_of_30"]:.2f}／30）')
    lines += ['', '來源QA修正版／模型原始回答層（每個平均值保留有效N）']
    for model_id, model in metrics['models'].items():
        layer = model['layers']['model']
        lines.append(f'\n{model_id}')
        for key in ('faithfulness', 'judge_answer_relevance', 'bge_m3_cosine'):
            value = layer[key]
            lines.append(f'{key}: {value["mean"]:.6f} (N={value["n"]})')
        value = model['raw_schema']
        lines.append(f'原始JSON格式通過：{value["success_n"]}/{value["n"]} ({value["rate"]:.2%})')
        for key in ('logical_accuracy', 'arithmetic_accuracy'):
            value = layer[key]
            lines.append(f'{key} 條件式：{value["correct_n"]}/{value["conditional_n"]} ({value["conditional_accuracy"]:.2%})')
            for field in ('fixed_content_success', 'fixed_validated_success'):
                rate = value[field]
                lines.append(f'{key} {field}: {rate["success_n"]}/{rate["n"]} ({rate["rate"]:.2%})')
        for key in ('source_50_content_correct_rate', 'source_50_task_success'):
            value = layer[key]
            lines.append(f'{key}: {value["success_n"]}/{value["n"]} ({value["rate"]:.2%})')
        for key in ('ttft_seconds', 'tps', 'peak_system_ram_gib', 'peak_dedicated_vram_gib'):
            value = model['timing_memory'][key]
            lines.append(f'{key}: {value["mean"]:.6f} (N={value["n"]})')
    lines += [
        '', '結案報告可引用文字：',
        '本計畫於同一套v6系統及本次硬體環境下，完成4個模型、每模型180題，共720次最終推論評估。依品質70%、效能30%的探索性加權方案，Qwen2.5-Coder-7B-Instruct（M2）以80.29分列本輪選型第一；該分數為相對選型分，並非專業答對率。來源QA修正版中，M2於50題來源核驗子集之內容符合率為19/50（38%），內容與程式驗證均通過為14/50（28%）。',
        '', '引用範圍與限制：',
        'Human Gold為0；50題依賴10個來源群組、3個原始檔案，並非獨立專家驗證或未見保留測試。',
        '共用檢索P@5為0.350，僅12題60段AI輔助原文審查；不得外推180題或用來區分模型。',
        '條件式準確率與固定分母任務成功率需分開；原始模型回答與系統輸出需分開。',
        '不同模型有效N不同；加權選型使用共同有效題配對數據，請勿以全體均值直接重算選型分數。',
        'TTFT不含預先完成的檢索；RAM/VRAM為系統/設備採樣峰值平均，非模型程序專屬用量；Shared GPU Memory維持N/A。',
        '70/30由使用者確認；子權重及正規化屬明列選型假設，不得稱為事前註冊正式綜合評測或統計顯著性。',
        '', '留存內容：',
        f'final_evaluation_evidence.zip：兩個來源目錄完整封存，共{len(entries)}個檔案，包括Excel、原始回答、串流、逐題指標、評分規則、診斷及既有驗證紀錄。',
        'final_results_record.json：完整精度統計、模型/系統分層、加權紀錄與封存資訊。',
        'evidence_manifest.json：每個封存檔案的相對路徑、大小與SHA256，可逐項核對。',
        f'封存SHA256：{summary["archive_sha256"]}',
        '已讀回封存全部檔案核對SHA256，並重新核對來源檔案。既有636項受保護資料的驗證沿用原評測紀錄，本次未重新宣稱驗證。',
        '本次僅留存既有結果，未重跑推論、變更語料或切換部署模型。封存目前位於同一工作區，並非異地備份。',
    ]
    (out / '結案報告引用說明.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    print(json.dumps({'directory': str(out), 'files': len(entries), 'archive_bytes': summary['archive_bytes'], 'sha256': summary['archive_sha256']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
