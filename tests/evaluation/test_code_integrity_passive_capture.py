import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

class Capture(unittest.TestCase):
    def test_read_only_command(self):
        p=Path(__file__).resolve().parents[2]/'scripts/phase19b_r2_execute.py'
        text=p.read_text(encoding='utf-8')
        self.assertIn('Get-WinEvent -FilterXml',text)
        self.assertIn("status='collected'",text)
        for command in ('Set-MpPreference','Set-RuleOption','Set-ItemProperty','Unblock-File','Clear-WinEvent'):
            self.assertNotIn(command,text)
    def test_no_events_distinct_from_unavailable(self):
        text=(Path(__file__).resolve().parents[2]/'scripts/phase19b_r2_execute.py').read_text(encoding='utf-8')
        self.assertIn('NoMatchingEventsFound',text);self.assertIn("'unavailable'",text)
    def test_native_query_uses_utc_z(self):
        from scripts.phase19b_r2_native_monitor_v2 import utc_z
        self.assertEqual(utc_z('2026-10-07T15:01:00+08:00'),'2026-10-07T07:01:00.000000Z')
    def test_native_nonempty_event_preserved(self):
        from scripts.phase19b_r2_native_monitor_v2 import query
        xml='''<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System><Provider Name="Microsoft-Windows-CodeIntegrity"/><EventID>3033</EventID><EventRecordID>99</EventRecordID><TimeCreated SystemTime="2026-10-07T07:01:00Z"/></System><EventData/></Event>'''
        with patch('scripts.phase19b_r2_native_monitor_v2.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=xml,stderr='')) as call:
            events,expression=query('2026-10-07T07:00:00+00:00','2026-10-07T07:02:00+00:00')
        self.assertEqual(events[0]['record_id'],99)
        self.assertEqual(events[0]['event_id'],3033)
        self.assertIn('raw_event_xml',events[0])
        self.assertIn('07:00:00.000000Z',expression)
        self.assertEqual(call.call_args.args[0][0],'wevtutil.exe')
