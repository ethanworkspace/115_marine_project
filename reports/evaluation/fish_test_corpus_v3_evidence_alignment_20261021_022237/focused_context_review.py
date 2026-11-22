"""Explicit content review of 60 existing returned chunks (12 purposive questions).
Not random, not independent human truth, not an estimate for all 180 questions.
"""
REVIEWS={
'FT-tilapia-Q09':[
 (1,'FULL_SUPPORT','Three specified avoided operations are all explicit.'),
 (0,'TOPICAL_ONLY','Windbreak location/angle is prevention infrastructure, not one of the requested avoided operations.'),
 (0,'TOPICAL_ONLY','Post-cold removal of fish bodies does not give the requested avoided operations during the event.'),
 (0,'TOPICAL_ONLY','Pre-winter harvest and stocking economics do not supply the three event-time avoided operations.'),
 (0,'TOPICAL_ONLY','The emergency temperature trigger is not the requested set of avoided operations.')],
'FT-tilapia-Q10':[
 (1,'FULL_SUPPORT','Explicit below-15°C trigger and warming example.'),
 (0,'TOPICAL_ONLY','Avoided operations do not specify the requested emergency threshold or warming action.'),
 (0,'TOPICAL_ONLY','Windbreak angle/location supplies neither the requested temperature trigger nor an event-time emergency measure.'),
 (0,'TOPICAL_ONLY','Post-event fish-body removal is a different operation, with no emergency temperature trigger.'),
 (0,'TOPICAL_ONLY','Historical low-temperature bacterial disease prevention supplies no requested FA-385 emergency temperature trigger; drug claims not adopted.')],
'FT-mullet-Q01':[
 (1,'FULL_SUPPORT','The exact first-year 1–2萬尾/公頃 density is present.'),
 (0,'IRRELEVANT','GSI and egg diameter describe reproductive maturity, not first-year pond density.'),
 (0,'TOPICAL_ONLY','DO reference and power backup do not provide the first-year tails/ha value.'),
 (0,'TOPICAL_ONLY','Turbidity/oxygen stress mechanisms do not provide first-year density.'),
 (0,'TOPICAL_ONLY','Feed mass percentages for a mixed pond are not stocking density by age.')],
'FT-mullet-Q17':[
 (1,'FULL_SUPPORT','The Q&A explicitly says existing nutrition should suffice and to contact the feed company for formula changes.'),
 (0,'TOPICAL_ONLY','Microalgae cultivation/water colour management is not advice about changing the commercial fish-feed formula.'),
 (0,'TOPICAL_ONLY','Pond sediment/organic oxygen demand is not commercial feed formulation advice.'),
 (0,'TOPICAL_ONLY','Daily feeding mass percentage does not answer whether/how to change the feed formulation.'),
 (0,'IRRELEVANT','Mitochondrial lineage labels concern population identity, not nutrition formulation.')],
'FT-grouper-Q09':[
 (1,'FULL_SUPPORT','Virus-free broodstock/healthy fry and egg/equipment/water hygiene directly supply requested biosecurity measures; old no-vaccine sentence is excluded from the reference.'),
 (0,'TOPICAL_ONLY','Genetic selection/inbreeding prevention is not pathogen-free seed or equipment biosecurity.'),
 (1,'PARTIAL_SUPPORT','Experimental virus inactivation and removal of residual disinfectant support the water/egg hygiene element only; numerical doses are not adopted as current legal advice.'),
 (0,'TOPICAL_ONLY','Nursery cage sizes and stocking counts do not establish seed health or equipment hygiene.'),
 (0,'TOPICAL_ONLY','Nitrification oxygen/filter maintenance does not establish pathogen-free seed or equipment disinfection.')],
'FT-grouper-Q15':[
 (1,'FULL_SUPPORT','Organic sediment/remnant feed causes oxygen consumption, water deterioration and parasite/bacterial risk.'),
 (1,'PARTIAL_SUPPORT','The instruction to remove bottom organic sludge supports the sediment-control element; the historical chemical dose is not adopted.'),
 (0,'TOPICAL_ONLY','Wind concentrates floating residues; this does not establish the requested organic-load/oxygen/pathogen risks.'),
 (0,'CONDITION_MISMATCH','Egg-incubation density and aeration conditions are not the stated high-density growout pond situation.'),
 (0,'TOPICAL_ONLY','A heading saying indoor high-density culture contains no substantive risk information.')],
'FT-milkfish-Q01':[
 (1,'FULL_SUPPORT','14.8°C can be compared with the explicit below-15°C emergency trigger and warming example.'),
 (0,'TOPICAL_ONLY','General avoided operations do not supply the requested emergency trigger.'),
 (0,'TOPICAL_ONLY','Removing fish bodies after the cold event supplies no temperature trigger or warming measure.'),
 (0,'TOPICAL_ONLY','Preventive windbreak specification alone supplies no emergency temperature trigger.'),
 (0,'TOPICAL_ONLY','Conditional pond thermal stratification describes a mechanism but no requested emergency trigger/action.')],
'FT-milkfish-Q06':[
 (1,'FULL_SUPPORT','Original historical Q&A explicitly gives pH7.5–9.5 for survival adaptation, supporting comparison with 9.2.'),
 (0,'TOPICAL_ONLY','Ammonia/nitrite case values do not establish the milkfish pH adaptation range.'),
 (0,'TOPICAL_ONLY','Algae/pH variation and water treatment discussion do not give the requested adaptation boundaries.'),
 (0,'TOPICAL_ONLY','Raising pH with lime is not evidence of the species adaptation range.'),
 (0,'IRRELEVANT','Mixed-culture stocking density is unrelated to the requested pH interval.')],
'FT-eel-Q05':[
 (1,'FULL_SUPPORT','Explicit Japanese-eel first grading after two months, then each 1–1.5 months.'),
 (1,'PARTIAL_SUPPORT','Clause (3) explicitly concerns Japanese eel and gives the requested timing; adjacent giant-mottled-eel temperature/feeding statements are not transferred.'),
 (1,'PARTIAL_SUPPORT','Clause (3) explicitly gives the Japanese-eel grading protocol; other clauses are not applicable reference facts.'),
 (0,'IRRELEVANT','Historical artificial reproduction/seed origin does not give a grading schedule.'),
 (0,'CONDITION_MISMATCH','Air-transport packing and shipment duration are different conditions from growout grading.')],
'FT-eel-Q03':[
 (1,'FULL_SUPPORT','The physical floating-feed description explicitly says over30minutes; no biological rate is transferred.'),
 (1,'PARTIAL_SUPPORT','The floating-feed section repeats over30minutes; feeding-rate and giant-eel biology statements are excluded.'),
 (1,'PARTIAL_SUPPORT','The floating-feed section repeats the requested physical duration; other biological claims are excluded.'),
 (0,'TOPICAL_ONLY','Time until feed is eaten and feed transition are not the physical flotation duration.'),
 (0,'TOPICAL_ONLY','Advice about transition to floating pellets supplies no flotation duration.')],
'FT-seabass-Q01':[
 (1,'FULL_SUPPORT','Lates calcarifer growth range28–32°C directly contains30°C.'),
 (0,'TOPICAL_ONLY','Salinity is a different environmental variable from requested temperature.'),
 (0,'TOPICAL_ONLY','Fry length and stocking density supply no temperature status.'),
 (0,'CONDITION_MISMATCH','Short-term market holding/live transport advice is not the manual growout optimum.'),
 (0,'SPECIES_MISMATCH','37°C/20–45°C are bacterial culture temperatures for Bacillus, not Lates physiology.')],
'FT-seabass-Q03':[
 (1,'FULL_SUPPORT','The finite source fact explicitly states Lates salinity≥5psu, supporting comparison with4psu.'),
 (0,'TOPICAL_ONLY','pH chemistry/day cycle is not a salinity recommendation.'),
 (0,'TOPICAL_ONLY','Fry size/density is not the requested salinity threshold.'),
 (0,'TOPICAL_ONLY','Temperature and secondary infection risk are not the requested salinity threshold.'),
 (0,'CONDITION_MISMATCH','Market-holding/transport conditions do not give the manual growout salinity boundary.')]
}

def reviewed_label(qid,rank,cid):
 import json,hashlib
 from pathlib import Path
 w=Path(__file__).resolve().parent
 b=json.loads((w/'focused_context_review_bindings.json').read_text(encoding='utf-8'))
 assert hashlib.sha256((w/'retrieval_results_alignment_final_180.jsonl').read_bytes()).hexdigest()==b['retrieval_sha256'],'Frozen retrieval changed; labels cannot be transferred by rank.'
 rows=REVIEWS.get(qid)
 if rows:assert b['expected_chunk_ids_by_rank'][qid][rank-1]==cid,'Chunk/rank binding mismatch'
 return rows[rank-1] if rows and rank<=len(rows) else None
