from numeric_grounding_v3 import numeric
def test_temperature_punctuation_preserves_whole_values():assert numeric('30°C，30°C，28–32°C')==['30','30','28','32']
def test_decimal_and_thousands():assert numeric('1.5°C、120,000尾、1,500,000尾')==['1.5','120000','1500000']
def test_ids_are_not_values():
 ids=['TFRI-114846-0452-C02','M17-SEABASS-LIMITED-FACTS-seabass_temperature-C01']
 assert numeric('依'+ids[0]+'與'+ids[1]+'，28°C',ids)==['28']
def test_unverified_actual_number_not_removed():assert numeric('使用3%稀鹽水，30°C')==['3','30']
def test_enumeration_not_decimal():assert numeric('建議：1. 避免投餌；2. 換水。1.5°C')==['1.5']
def test_numeric_tail_not_extracted_from_alphanumeric():assert numeric('C01、M17、28°C')==['28']
def test_ph_and_unrecognized_id_values_not_silently_hidden():assert '7' in numeric('pH-7，28°C')
def test_document_number_is_not_water_temperature():assert numeric('手冊17記載28°C')==['28']
