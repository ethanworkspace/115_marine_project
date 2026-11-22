"""Source-blind-to-generator Codex review of fixed 12-question actual contexts."""
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
import evaluate_unified_rag_v6 as ev

# Labels were assigned after reading every actual passage and question, with no
# M1-M4 evaluation answer used. IDs/ranks/quotes are validated programmatically.
# This is explicit AI-assisted exploratory review, never human reference truth.
D={
 'FT-tilapia-Q09':[
  (1,'V4-25a18d90303d5c4c0f440760','PARTIAL_SUPPORT','冬季低溫期，養殖池須避免捕撈、搬移、清池等工作，以免對魚體造成傷害。','原文提供低溫期應避免的三項魚塭作業，屬另一官方歷史文獻的明確部分支持；不等同漁業署指定的投餌、換水、水車三項。'),
  (0,'V4-ad74ff5d59d4f85dc8818e72','TOPICAL_ONLY',None,'僅為防寒頁前言與越冬風險，未列應避免的魚塭操作。'),
  (0,'V4-954e405c6dca459148dcd2d6','CONDITION_MISMATCH',None,'敘述收成前肥滿度、臭土味、投餌與換水管理，不能作為寒流期間三項禁忌操作。'),
  (0,'V4-396b69bc68abf1aa341e647b','IRRELEVANT',None,'法規內容是生產區土地劃入劃出及規劃書，無寒流魚塭操作資訊。'),
  (0,'V4-43a8fe91993d7e666d5e2f69','TOPICAL_ONLY',None,'描述吳郭魚低溫病害與死亡史，沒有回答應避免哪些操作。')],
 'FT-tilapia-Q10':[
  (0,'V4-ad74ff5d59d4f85dc8818e72','TOPICAL_ONLY',None,'防寒前言沒有緊急水溫門檻或可具體舉出的緊急措施。'),
  (0,'V4-3815462e1e8de84a1aba37de','CONDITION_MISMATCH',None,'緊急應變適用廢污水危害與主管機關通知，不適用寒流水溫門檻。'),
  (0,'V4-25a18d90303d5c4c0f440760','CONDITION_MISMATCH',None,'15至30等數值是水黴菌生長或感染條件，不能轉作魚塭防寒15°C緊急門檻。'),
  (0,'V4-4f19afe47da019d21a5134d2','TOPICAL_ONLY',None,'說明疾病、提前放養與寒流前收成，未給出緊急水溫門檻或相應處置。'),
  (0,'V4-8902e1395c5f128db0759841','IRRELEVANT',None,'漁業法資源管理公告事項與寒流緊急水溫無關。')],
 'FT-mullet-Q01':[
  (1,'TFRI-114846-0452-C02','FULL_SUPPORT','烏魚養殖第一年密度每公頃可達1－2萬尾','直接記載第一年、每公頃與1至2萬尾，條件及單位齊全。'),
  (1,'V4-90136523762732d64123961c','FULL_SUPPORT','烏魚1 齡養殖放養密度每公頃約可在1 ～ 2 萬尾','原章節給出一齡烏魚密度，並保留依現地狀況調整之條件。'),
  (1,'V4-fc8963f843cbac3458c85eaf','FULL_SUPPORT','烏魚1 齡養殖放養密度每公頃約可在1 ～ 2 萬尾','完整手冊同段亦支持；與章節檔是重複知識，不當作獨立來源。'),
  (0,'TFRI-114846-0452-C10','IRRELEVANT',None,'益生菌商品與聯絡資訊沒有第一年放養密度。'),
  (0,'V4-c9485b96da722bde4aa41f16','CONDITION_MISMATCH',None,'600至800尾是繁殖用種魚池，不能套用第一年食用烏魚放養密度。')],
 'FT-mullet-Q17':[
  (1,'TFRI-114846-0452-C04','FULL_SUPPORT','目前市售烏魚飼料營養成分應已足夠，若想改變配方可跟飼料公司另行接洽。','直接回答配方變更應聯絡飼料公司，非自行大幅改配方。'),
  (0,'TFRI-114846-0452-C10','IRRELEVANT',None,'益生菌不需自行培養與改變烏魚飼料配方不是同一資訊需求。'),
  (0,'V4-dc5a43ebed3568bb672cdbe7','TOPICAL_ONLY',None,'四定投餌及馴餌管理未說明變更飼料配方應採的作法。'),
  (0,'V4-fc9c6d372d3ec1b612452a45','TOPICAL_ONLY',None,'同段投餵原則不是配方變更的建議或營養配方依據。'),
  (0,'TFRI-114846-0050-C02','CONDITION_MISMATCH',None,'段落是微藻與綠水培養、肥料及水色調控，不能當成烏魚配合飼料改配方建議。')],
 'FT-grouper-Q09':[
  (1,'V4-ac4dec33e976e2388b629f9a','PARTIAL_SUPPORT','在石斑魚放養前，需進行環境的消毒','明確支持放養前消毒的一部分；原頁有雙欄混排，僅採此可定位非劑量陳述，不將混欄數值當藥方。'),
  (1,'TFRI-114846-0235-C03','FULL_SUPPORT','篩選無帶病毒種魚進行繁殖十分重要，另配合洗卵、養殖用具、生物餌料、池水消毒等飼養管理措施','直接支持健康種魚與卵、用具、餌料、池水生物安全控制，須保留病毒風險背景。'),
  (1,'V4-ed19a1a530ed83d9c6daeccd','PARTIAL_SUPPORT','系統經確實的消毒防疫且減少外來水源的使用','提供種苗場系統消毒與減少外來水源之部分防疫措施；不是完整種魚篩檢答案。'),
  (1,'TFRI-114846-0235-C02','PARTIAL_SUPPORT','因此發病魚應隔離飼養','直接支持隔離與原段的器具、餌料消毒，限定該病毒感染背景，不推算用藥劑量。'),
  (0,'TFRI-114846-0389-C02','TOPICAL_ONLY',None,'種質退化與近親育種品質未提供帶病毒種苗篩選、感染隔離或器具生物安全要求。')],
 'FT-grouper-Q15':[
  (0,'V4-978234a2ef392b427b5faadc','SOURCE_SCOPE_MISMATCH',None,'本條是主管機關公共水體監測與禁捕職責，不是高密度魚池殘餌底泥的養殖風險提醒。'),
  (1,'TFRI-114846-0900-C05','PARTIAL_SUPPORT','清池後應除去底部之有機物污泥','支持底部有機物清除這項管理提醒；保留清池後條件，不採後續消毒劑量作現行處方。'),
  (0,'V4-f6db88a0e8d71873dbb68a8f','CONDITION_MISMATCH',None,'說明種魚場進水之沉澱砂濾，未處理既有高密度池殘餌、底泥累積與水質波動風險。'),
  (0,'TFRI-114846-0362-C04','TOPICAL_ONLY',None,'解釋風尾浮沫及懸浮殘餌聚集，未提供題目所要求的高密度、底泥累積與波動風險或處理提醒。'),
  (0,'TFRI-114846-0714-C01','TOPICAL_ONLY',None,'僅說明作水牽涉多項因素及無法答覆，沒有此情境的實質風險提醒。')],
 'FT-milkfish-Q01':[
  (0,'V4-ad74ff5d59d4f85dc8818e72','TOPICAL_ONLY',None,'防寒前言沒有15°C門檻或緊急措施，無法據以判斷14.8°C。'),
  (0,'TFRI-114846-0414-C01','SPECIES_MISMATCH',None,'原文數值與耐寒試驗是黃臘鰺，不能因Metadata標為虱目魚就套用。'),
  (0,'V4-3815462e1e8de84a1aba37de','SOURCE_SCOPE_MISMATCH',None,'廢污水緊急應變法規不是虱目魚寒流緊急門檻。'),
  (0,'TFRI-114846-0902-C01','TOPICAL_ONLY',None,'池水溫度分層機制沒有指定門檻或需採的緊急措施。'),
  (0,'V4-414f2d49079d7a044463d6ae','TOPICAL_ONLY',None,'循環水設施補助目的沒有14.8°C判斷或防寒緊急作法。')],
 'FT-milkfish-Q06':[
  (1,'TFRI-114846-0896-C01','FULL_SUPPORT','pH基本上以7.5－9.5範圍均可以適應生存。','提供虱目魚基本可適應範圍，可判9.2位於其中；不等同最佳或保證安全。'),
  (0,'TFRI-114846-0896-C02','TOPICAL_ONLY',None,'體型、飼料、乾旱及水質建議沒有虱目魚pH可適應範圍。'),
  (0,'TFRI-114846-0418-C01','CONDITION_MISMATCH',None,'2.94與0.98是總氨及亞硝酸，不是pH範圍。'),
  (0,'TFRI-114846-0418-C03','SPECIES_MISMATCH',None,'段落是河鯰及鮭鱒亞硝酸耐受值，既非虱目魚也非pH門檻。'),
  (0,'TFRI-114846-0342-C02','TOPICAL_ONLY',None,'pH升高原因及藻類處理沒有提供本題要求的基本可適應數值範圍。')],
 'FT-eel-Q03':[
  (0,'TFRI-114846-0257-C03','SPECIES_MISMATCH',None,'本段是虎皮蛙與蝌蚪飼育；鰻魚粉是餌料成分，不能當成鰻魚浮料漂浮時間證據。'),
  (0,'V4-314e145db68cab96f60ffc94','IRRELEVANT',None,'天然災害貸款額度與期限不支持飼料漂浮時間。'),
  (0,'TFRI-114846-0278-C01','CONDITION_MISMATCH',None,'1至1.5小時是鰻魚吃完飼料的供餌原則，不等於浮性粒料物理漂浮時間。'),
  (0,'TFRI-114846-0080-C02','CONDITION_MISMATCH',None,'3至4小時是少量再次投餵間隔，沒有記載浮性粒料漂浮時長。'),
  (0,'V4-1723377f195cfafa7ca96e1c','TOPICAL_ONLY',None,'浮於水表是病魚行為與病徵，不是浮性粒狀飼料。')],
 'FT-eel-Q05':[
  (1,'TFRI-114846-0348-C09','FULL_SUPPORT','傳統的日本鰻養殖，是放養後2個月開始篩選，然後每約1個月或1個半月篩選1次。','直接給出初次2個月與後續1至1.5個月，三重縣例子不取代傳統頻率。'),
  (1,'TFRI-114846-0436-C05','FULL_SUPPORT','傳統的日本鰻養殖，是放養後2個月開始篩選，然後每1個月或1個半月篩選1次。','同一傳統日本鰻頻率敘述，保留原紀錄關係。'),
  (1,'TFRI-114846-0472-C06','FULL_SUPPORT','傳統的日本鰻養殖，是放養後2個月開始篩選，然後每約1個月或1個半月篩選1次。','提供同一管理頻率；與其他問答之文字重複另標示依賴。'),
  (1,'V4-87b211c77392b7aa9c5d1a31','PARTIAL_SUPPORT','最好每隔1-1.5 個月即作大小篩選','支持後續篩選頻率；原件前言另核對主要對象白鰻Anguilla japonica、泥土池，不把重量分級當作固定2個月初篩。'),
  (0,'V4-684be98857c6a98a4b4717a4','CONDITION_MISMATCH',None,'成鰻投餌比例與上市體型沒有初次及後續篩選頻率。')],
 'FT-seabass-Q01':[
  (1,'V4-82a00a5bfc19f85ed83576d9','FULL_SUPPORT','金目鱸養殖的最佳水溫28 ～32℃','具金目鱸專屬最佳範圍，30°C位於其中。'),
  (1,'V4-df6ba28ca332d63dc15ffdf6','FULL_SUPPORT','金目鱸養殖的最佳水溫28 ～32℃','章節與完整手冊同段支持；不是第二份獨立生理實驗。'),
  (1,'M17-SEABASS-LIMITED-FACTS-seabass_temperature-C01','FULL_SUPPORT','最佳成長水溫28–32°C','有限事實記錄有範圍且明限金目鱸，不推廣所有鱸魚。'),
  (0,'V4-5c9b7e07fe95712875dfc454','TOPICAL_ONLY',None,'序言描述風險與手冊目的，沒有最佳水溫數值。'),
  (0,'V4-4ba236dde18b8a77e86fb621','TOPICAL_ONLY',None,'不耐寒與防疫前言沒有30°C所需的最佳範圍。')],
 'FT-seabass-Q03':[
  (1,'M17-SEABASS-LIMITED-FACTS-seabass_salinity-C01','FULL_SUPPORT','建議鹽度≥5 psu較佳。','直接提供5 psu以上較佳，可判4 psu低於建議；不宣稱必死。'),
  (1,'V4-953644b7ad7b5d6e20ef4c74','FULL_SUPPORT','建議維持鹽度在5 psu 以上較佳。','原文給出金目鱸場域與鹽度條件。'),
  (1,'V4-deb668261a87b17c7d5cb9b0','FULL_SUPPORT','建議維持鹽度在5 psu 以上較佳。','完整手冊同段支持，另記重複依賴。'),
  (0,'V4-f4c2f020ba5e37996bc874b4','TOPICAL_ONLY',None,'養殖型態、種苗與生物安全背景沒有5 psu數值或4 psu判斷。'),
  (0,'V4-5c9b7e07fe95712875dfc454','TOPICAL_ONLY',None,'序言沒有鹽度門檻，不能只因同魚種就視為支持。')],
}

def main():
    import collections,sqlite3
    w=ev.work();rows=ev.jl(w/'shared_contexts_180.jsonl');profiles={x['question_id']:x for x in ev.jl(w/'question_requirement_profiles_reviewed_180.jsonl')};labels=[];all_labels=[];per_question=[]
    for q in rows:
        decisions=D.get(q['question_id']);chosen=[]
        for c in q['top5']:
            common={'run_id':w.name,'question_id':q['question_id'],'chunk_id':c['chunk_id'],'rank':c['rank'],'source_id':c['source_id'],'source_record_id':c['source_record_id'],'source_sha256':c['source_sha256'],'source_version':c['source_version'],'context_digest':q['context_digest'],'context_text_sha256':ev.digest(c['source_quote']),'source_species_metadata':c['species_scope'],'required_answer_elements':profiles[q['question_id']]['required_answer_elements'],'exact_locator':c['exact_locator'],'not_human_gold':True}
            if decisions:
                value,cid,support,quote,reason=decisions[c['rank']-1];assert cid==c['chunk_id'],'Rank/ID binding mismatch'
                start=c['source_quote'].find(quote) if quote else None
                if value==1:assert quote and start>=0 and c['source_quote'][start:start+len(quote)]==quote,'Evidence quote mismatch: '+cid
                label={**common,'relevance_label':value,'support_label':support,'reason':reason,'exact_evidence_span':quote,'quote_start':start,'quote_end':start+len(quote) if quote else None,'quote_verified':True if quote else None,'annotation_method':'CODEX_DIRECT_QUESTION_REQUIREMENT_AND_SOURCE_REVIEW','verification_level':'AI_ASSISTED_EXPLORATORY_SOURCE_ALIGNMENT_NOT_HUMAN_GOLD','needs_independent_review':True,'original_source_text':c['source_quote']};labels.append(label);chosen.append(value)
            else:label={**common,'relevance_label':None,'support_label':'UNVERIFIED','reason':'Not individually reviewed in this 12-question exploratory sample; do not infer irrelevant from lexical overlap or reranker score','verification_level':'NOT_ANNOTATED_THIS_RUN'}
            all_labels.append(label)
        score=sum(chosen)/5 if len(q['top5'])==5 and len(chosen)==5 else None
        per_question.append({'question_id':q['question_id'],'species':q['species'],'category':q['category'],'context_count':len(q['top5']),'reviewed':len(chosen),'relevant':sum(chosen),'p_at_5':score,'lower_bound':sum(chosen)/5 if len(q['top5'])==5 else None,'upper_bound':(sum(chosen)+5-len(chosen))/5 if len(q['top5'])==5 else None,'reason':None if score is not None else 'NOT_FULL_TOP5' if len(q['top5'])<5 else 'UNVERIFIED_CONTEXT_LABELS','shared_across_all_four_models':True,'verification_level':'AI_ASSISTED_EXPLORATORY_NOT_HUMAN_GOLD'})
    assert len(labels)==60 and len({x['question_id'] for x in labels})==12
    for name,data in [('context_precision_labels_v6.jsonl',labels),('retrieved_context_relevance_labels.jsonl',all_labels),('context_precision_detailed.jsonl',per_question)]:
        with (w/name).open('w',encoding='utf-8') as f:
            for row in data:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    valid=[x for x in per_question if x['p_at_5'] is not None]
    species={s:{'n':len(g),'mean':sum(x['p_at_5'] for x in g)/len(g)} for s in {x['species'] for x in valid} if (g:=[x for x in valid if x['species']==s])}
    summary={'metric':'AI_ASSISTED_CONTEXT_PRECISION_AT_5','formula':'relevant_count / 5, only complete five binary reviewed labels','n_questions':len(valid),'n_reviewed_chunks':len(labels),'mean':sum(x['p_at_5'] for x in valid)/len(valid) if valid else None,'label_counts':dict(collections.Counter(x['relevance_label'] for x in labels)),'support_labels':dict(collections.Counter(x['support_label'] for x in labels)),'by_species':species,'unverified_returned_chunks':len(all_labels)-len(labels),'not_human_gold':True,'not_an_estimate_of_all_180_questions':True,'not_ai_classification_precision_or_recall':True,'no_generator_answers_used':True,'same_contexts_as_actual_720_run':True}
    ev.dump(w/'context_precision_summary.json',summary);ev.emit(summary)

if __name__=='__main__':main()
