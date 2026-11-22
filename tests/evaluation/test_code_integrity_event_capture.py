import unittest
from src.evaluation.edge.recovery19b1 import parse_event
class EventTest(unittest.TestCase):
    def test_preserves_xml_and_exact_UTC_policy_data(self):
        xml="""<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><TimeCreated SystemTime='2026-10-07T05:13:04Z'/><Correlation ActivityID='abc'/></System><EventData><Data Name='File Name'>x.dll</Data><Data Name='PolicyGUID'>id</Data><Data Name='Status'>0xc0e90002</Data></EventData></Event>"""
        r=parse_event(dict(raw_event_xml=xml,event_id=3077,timestamp='incorrect'))
        self.assertEqual(r['timestamp'],'2026-10-07T05:13:04Z');self.assertEqual(r['raw_event_xml'],xml)
        self.assertEqual(r['blocked_path'],'x.dll');self.assertEqual(r['policy_identifier'],'id')
        self.assertEqual(r['status_code'],'0xc0e90002');self.assertEqual(r['correlation_id'],'abc')
