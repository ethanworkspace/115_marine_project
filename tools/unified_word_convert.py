"""Read-only, macro-disabled conversion in a new Word instance, never the user's session."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
work = Path(json.loads((root / 'research_staging/unified_rag_build_pointer.json').read_text(encoding='utf-8'))['workspace'])
out = work / 'converted'
out.mkdir(exist_ok=True)
results = []
try:
    import win32com.client
    word = win32com.client.DispatchEx('Word.Application')
    word.Visible = False
    word.DisplayAlerts = 0
    word.AutomationSecurity = 3
    word.Options.UpdateLinksAtOpen = False
    for path in sorted((root / 'my_data').rglob('*')):
        if path.suffix.lower() not in ('.doc', '.odt'):
            continue
        rec = {'source': str(path), 'status': 'ERROR'}
        doc = None
        try:
            doc = word.Documents.Open(str(path.resolve()), ConfirmConversions=False, ReadOnly=True,
                                      AddToRecentFiles=False, Visible=False, NoEncodingDialog=True,
                                      PasswordDocument='', PasswordTemplate='')
            dest = out / (path.stem + '.pdf')
            doc.ExportAsFixedFormat(str(dest), 17, OpenAfterExport=False)
            rec.update(status='CONVERTED_READ_ONLY', pdf=str(dest))
        except Exception as exc:
            rec['error'] = repr(exc)
        finally:
            if doc is not None:
                doc.Close(False)
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    word.Quit()
except Exception as exc:
    results.append({'status': 'WORD_UNAVAILABLE', 'error': repr(exc)})
(work / 'word_conversion_results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
