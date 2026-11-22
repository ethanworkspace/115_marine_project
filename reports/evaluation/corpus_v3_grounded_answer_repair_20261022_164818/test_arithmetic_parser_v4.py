from arithmetic_parser_v4 import parse_arithmetic as parse
def c(unit,expected):return {'unit':unit,'expected':str(expected),'tolerance':'0.01'}
def test_width_result_not_range_operand():assert parse('最佳成長水溫區間寬度為4°C (32°C - 28°C)。',c('°C',4))['correct']
def test_width_result_not_later_source_range():assert parse('寬度為4°C。來源提供28至32°C的範圍。',c('°C',4))['correct']
def test_increment_result_not_later_management_threshold():assert parse('鹽度增量為21 ppt - 8 ppt = 13 ppt。來源建議出售前千分之20以上。',c('ppt',13))['correct']
def test_chinese_interval_phrase():assert parse('6個月大約有4個1.5個月的間隔。',c('個間隔',4))['correct']
def test_simplified_per_hectare_rate_not_total():assert not parse('每公顷20,000尾/公顷符合放養上限。',c('尾',60000))['evaluable']
def test_only_claimed_result_is_wrong():assert not parse('對應150,000尾。',c('尾',60000))['correct']
def test_wrong_dimension_explicit_total_is_incorrect():
 x=parse('最大總重量最多為6.0公斤/平方公里。',c('kg',780));assert x['evaluable'] and not x['correct'] and not x['unit_valid']
def test_selection_does_not_match_gold():
 x=parse('寬度為4°C，範圍28至32°C。',c('°C',32));assert x['parsed']=='4' and not x['correct'] and not x['selection_uses_expected_value']
def test_wrong_multiplication_equation_stays_wrong():assert not parse('超出 (600 m³ × 1.3 kg/m³) - 900 kg = 780 kg。',c('kg',120))['correct']
def test_unambiguous_single_number():assert parse('應提高至千分之21。',c('ppt',21))['correct']
def test_simplified_explicit_result():assert parse('3.5公顷鱼池每公顷4万尾，对应140,000尾。',c('尾',140000))['correct']
def test_english_result_variable_not_other_assignments():assert parse('official_limit = 15°C, measured_temp = 14.2°C, difference = 0.8°C',c('°C',.8))['correct']
def test_comparative_difference_not_inputs():assert parse('3 psu相較5 psu建議下限低2 psu。',c('psu',2))['correct']
def test_increase_not_target_concentration():assert parse('從8 ppt調到21 ppt，增加了13 ppt。',c('ppt',13))['correct']
