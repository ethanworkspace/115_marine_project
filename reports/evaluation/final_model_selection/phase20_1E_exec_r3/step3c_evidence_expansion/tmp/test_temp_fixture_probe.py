from pathlib import Path
def test_phase20_1e_temp_fixture_roundtrip(tmp_path):
    p=tmp_path/'fixture.txt'
    p.write_text('fixture-ok',encoding='utf-8')
    assert p.read_text(encoding='utf-8')=='fixture-ok'
    p.unlink()
    assert not p.exists()
