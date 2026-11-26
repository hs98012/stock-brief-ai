"""Only located footnotes may authorize exact semantic metric identity."""
from copy import deepcopy
import hashlib

import pytest

from app.evidence_requirements import fact_requirement_match, metric_form, table_requirements
from app.primitive_graph import comparison_candidates, comparison_fact_valid
from app.metric_annotations import annotate_metric_facts, annotation_valid
from tests.test_primitive_graph import page_grid
from tests.test_shared_metric_context import pack


def annotated_page(labels=('영업이익률3)', '순이익률3)'), notes=('3)',), explicit=True):
    p = page_grid(('2027F','2028F'), tuple('영업이익률' for _ in labels))
    # The raw fixture's unit inference is deliberately replaced with a real
    # ratio table, then rederived through the unchanged production extractor.
    words = p.extraction.provenance['selected_words']
    cells = p.extraction.provenance['native_tables'][0]['cells']
    entries = [(w['text'],w['bbox']) for w in words]
    for r in range(1,len(labels)+1):
        entries[r*4] = (labels[r-1],entries[r*4][1])
        cells[r*4]['text'] = labels[r-1]
        entries[r*4+1] = ('%',entries[r*4+1][1])
        cells[r*4+1]['text'] = '%'
    from tests.test_structured_cells import observed
    end = p.extraction.provenance['native_tables'][0]['bbox'][3]
    note_indices=[]
    for i,marker in enumerate(notes):
        y=end+4+i*18
        row=[('주:',[0,y,15,y+12])] if explicit else []
        row += [(marker,[20,y,30,y+12]),('보고기간 재작성',[35,y,170,y+12])]
        note_indices.append((len(entries),len(entries)+len(row)))
        entries+=row
    text,words=observed(entries)
    for i,(a,b) in enumerate(note_indices):
        for w in words[a:b]:w['line_id']=f'note:{i}'
    p.final_text=text
    p.extraction.final_text_sha256=hashlib.sha256(text.encode()).hexdigest()
    p.extraction.provenance['selected_words']=words
    p.extraction.provenance['index_segments']=[dict(char_start=0,char_end=len(text),kind='fact_quote')]
    from app.structured_cells import extract_cell_facts
    p.extraction.table_facts=extract_cell_facts(text,words,p.extraction.provenance['native_tables'],1)
    return p


def semantic(p):
    return annotate_metric_facts(p,p.extraction.table_facts)


@pytest.mark.parametrize('query,label',[('영업이익률','영업이익률3)'),('순이익률','순이익률3)')])
def test_actual_footnote_proof_authorizes_exact_canonical_match(query,label):
    p=annotated_page(); facts=semantic(p)
    f=next(f for f in facts if f['metric']==label and f['period']=='2027F')
    req=table_requirements(f'표의 2027F {query}은 얼마인가?')[0]
    assert fact_requirement_match(req,f)[0]
    identity=f['metric_identity']
    assert identity['raw_label']==label and identity['canonical_label']==query
    assert identity['annotation']=='3)' and identity['annotation_type']=='footnote'
    assert identity['proof_level']=='verified_annotation' and annotation_valid(f,p)
    assert f['metric']==label and f['metric_span']['quote']==label
    assert identity['definition_spans']


def test_shared_marker_preserves_distinct_base_labels_and_isolated_packs():
    p=annotated_page()
    result=pack(p,'표의 2027F와 2028F 영업이익률을 비교해줘.')
    assert result.coverage_complete
    facts=[f for item in result.evidence_pack for f in item.get('table_evidence',[])]
    assert facts and all(f['metric']=='영업이익률3)' for f in facts)
    assert all(x['metric']=='영업이익률3)' for f in facts for x in f['comparison_derivation']['primitive_cells'])
    assert {'영업이익률','순이익률'}=={f['metric_identity']['canonical_label'] for f in semantic(p)}


@pytest.mark.parametrize('label',['3개월 성장률','2023년 영업이익률','Level 3 Margin',
    '3분기','제3항','3년 평균','2차전지','1인당','Tier 1','Level 2'])
def test_semantic_numbers_are_not_stripped(label):
    assert metric_form(label)['surface']==label
    p=annotated_page((label,))
    facts=semantic(p)
    assert facts and all(f.get('metric_identity',{}).get('canonical_label',label)==label for f in facts)


def test_suffix_without_definition_stays_unverified_and_holds():
    p=annotated_page(notes=())
    f=semantic(p)[0]
    assert f['metric_identity']['proof_level']=='unverified_suffix'
    assert not pack(p,'표의 2027F와 2028F 영업이익률을 비교해줘.').coverage_complete


def test_plain_numbered_reference_is_not_a_verified_footnote():
    p=annotated_page(explicit=False)
    f=semantic(p)[0]
    assert f['metric_identity']['proof_level']=='probable_annotation'
    assert not fact_requirement_match(table_requirements('표의 2027F 영업이익률은 얼마인가?')[0],f)[0]


@pytest.mark.parametrize('labels,notes',[
    (('영업이익률1)','영업이익률2)'),('1)','2)')),
    (('영업이익률3)','영업이익률'),('3)',)),
])
def test_canonical_collision_holds_even_when_chain_values_agree(labels,notes):
    p=annotated_page(labels,notes)
    facts=semantic(p)
    assert facts and all(f['metric_identity']['rejection_reason']=='canonical_metric_collision' for f in facts)
    assert not pack(p,'표의 2027F와 2028F 영업이익률을 비교해줘.').coverage_complete


@pytest.mark.parametrize('query',['영업이익','이익률'])
def test_partial_or_fuzzy_similarity_does_not_authorize_equivalence(query):
    p=annotated_page(); f=semantic(p)[0]
    req=table_requirements(f'표의 2027F {query}은 얼마인가?')[0]
    assert not fact_requirement_match(req,f)[0]


@pytest.mark.parametrize('field,value',[
    ('raw_label','순이익률3)'),('canonical_label','매출액'),('canonical_label',''),('annotation','4)'),
    ('proof_level','probable_annotation'),('definition_spans',[]),
])
def test_identity_proof_tampering_is_rejected(field,value):
    p=annotated_page(); f=deepcopy(semantic(p)[0])
    f['metric_identity'][field]=value
    assert not annotation_valid(f,p)
    from app.evidence_bundle import _fact_spans
    assert not _fact_spans(p,f,table=True)


def test_deleted_identity_proof_cannot_bypass_pack_validation():
    p=annotated_page(); f=deepcopy(semantic(p)[0]);f.pop('metric_identity')
    assert not annotation_valid(f,p)


def test_definition_deletion_invalidates_previously_passing_comparison():
    p=annotated_page(); req=table_requirements('표의 2027F와 2028F 영업이익률을 비교해줘.')
    f=comparison_candidates(p,req)[0]
    assert comparison_fact_valid(f,p)
    p.extraction.provenance['selected_words']=[w for w in p.extraction.provenance['selected_words']
        if not str(w['line_id']).startswith('note:')]
    assert not comparison_fact_valid(f,p)
    assert not pack(p,'표의 2027F와 2028F 영업이익률을 비교해줘.').coverage_complete


def test_marker_source_change_invalidates_previous_proof():
    p=annotated_page(); f=semantic(p)[0]
    for w in p.extraction.provenance['selected_words']:
        if w['text']=='3)':w['text']='4)'
    assert not annotation_valid(f,p)


def test_query_canonical_fields_must_agree_with_its_literal_surface():
    p=annotated_page(); f=semantic(p)[0]
    req=table_requirements('표의 2027F 영업이익률은 얼마인가?')[0]
    req['metric']['surface']='영업이익'
    assert not fact_requirement_match(req,f)[0]


def test_empty_base_marker_is_never_a_metric():
    p=annotated_page(('3)',))
    assert not semantic(p)


def test_superscript_in_separate_source_span_with_definition_is_verified():
    p=annotated_page(('영업이익률',),notes=('³',))
    from app.structured_cells import extract_cell_facts
    # Separate raised marker in the same observed metric cell; no row geometry edit.
    text=p.final_text+'\n³';start=len(p.final_text)+1
    metric=next(w for w in p.extraction.provenance['selected_words'] if w['text']=='영업이익률')
    metric['bbox'][2]-=20
    box=metric['bbox']
    marker=dict(text='³',bbox=[box[2]+1,box[1]-1,box[2]+5,box[1]+4],source='native',confidence=99,
        line_id=metric['line_id'],char_start=start,char_end=start+1)
    p.final_text=text;p.extraction.final_text_sha256=hashlib.sha256(text.encode()).hexdigest()
    p.extraction.provenance['selected_words'].append(marker)
    p.extraction.table_facts=extract_cell_facts(text,p.extraction.provenance['selected_words'],p.extraction.provenance['native_tables'],1)
    facts=semantic(p)
    assert facts and facts[0]['metric_identity']['proof_level']=='verified_annotation'
    assert facts[0]['metric_identity']['annotation']=='³'
    assert facts[0]['metric_identity']['marker_span']['char_start']==start
    assert facts[0]['metric_identity']['canonical_label']=='영업이익률'


def test_collision_with_rejected_sibling_chain_cannot_be_ignored():
    p=annotated_page(('영업이익률1)','영업이익률2)'),('1)','2)'))
    p.extraction.table_facts=[f for f in p.extraction.table_facts if f['metric']=='영업이익률1)']
    assert all(f['metric_identity']['rejection_reason']=='canonical_metric_collision' for f in semantic(p))
    assert not pack(p,'표의 2027F와 2028F 영업이익률을 비교해줘.').coverage_complete


def test_raw_source_change_with_updated_page_hash_breaks_old_proof():
    p=annotated_page();f=deepcopy(semantic(p)[0])
    p.final_text=p.final_text.replace('영업이익률3)','영업이익률4)')
    p.extraction.final_text_sha256=hashlib.sha256(p.final_text.encode()).hexdigest()
    for w in p.extraction.provenance['selected_words']:
        if w['text']=='영업이익률3)':w['text']='영업이익률4)'
    assert not annotation_valid(f,p)
    assert not pack(p,'표의 2027F와 2028F 영업이익률을 비교해줘.').coverage_complete


def test_duplicate_definition_or_remote_definition_is_not_verified():
    p=annotated_page(notes=('3)','3)'))
    assert all(f['metric_identity']['proof_level']!='verified_annotation' for f in semantic(p))
    p=annotated_page()
    for w in p.extraction.provenance['selected_words']:
        if str(w['line_id']).startswith('note:'):
            w['bbox'][1]+=200;w['bbox'][3]+=200
    assert all(f['metric_identity']['proof_level']=='unverified_suffix' for f in semantic(p))


def test_unsafe_definition_span_cannot_authorize_annotation():
    p=annotated_page()
    w=next(w for w in p.extraction.provenance['selected_words'] if w['text']=='3)')
    p.extraction.provenance['unsafe_spans']=[dict(char_start=w['char_start'],char_end=w['char_end'])]
    assert all(f['metric_identity']['proof_level']!='verified_annotation' for f in semantic(p))


def test_proof_without_unique_row_chain_cannot_fill_requirements():
    p=annotated_page();f=deepcopy(semantic(p)[0]);f['value_span']['bbox'][1]+=100
    from app.evidence_bundle import _fact_spans
    assert not _fact_spans(p,f,table=True)


def test_separate_superscript_alone_is_probable_and_holds():
    p=annotated_page(('영업이익률³','순이익률³'),notes=())
    assert not pack(p,'표의 2027F와 2028F 영업이익률을 비교해줘.').coverage_complete


def test_removed_definition_spans_cannot_satisfy_pack_even_if_metadata_is_forged():
    p=annotated_page();f=deepcopy(semantic(p)[0])
    f['metric_identity']['definition_spans'][0]['quote']='위조'
    from app.evidence_bundle import _fact_spans
    assert not _fact_spans(p,f,table=True)


def test_canonical_collision_across_different_metric_label_columns_holds():
    p=annotated_page(('영업이익률1)','영업이익률2)'),('1)','2)'))
    cells=p.extraction.provenance['native_tables'][0]['cells'];words=p.extraction.provenance['selected_words']
    # Alternate label/unit columns on the second row while preserving every
    # row/period/value bbox and the table's ordered physical column topology.
    a,b=cells[8],cells[9]
    a['column'],b['column']=b['column'],a['column']
    a['bbox'],b['bbox']=b['bbox'],a['bbox']
    words[8]['bbox'],words[9]['bbox']=words[9]['bbox'],words[8]['bbox']
    from app.structured_cells import extract_cell_facts
    p.extraction.table_facts=extract_cell_facts(p.final_text,words,p.extraction.provenance['native_tables'],1)
    assert len(p.extraction.table_facts)==4
    assert all(f['metric_identity']['rejection_reason']=='canonical_metric_collision' for f in semantic(p))
    assert not pack(p,'표의 2027F와 2028F 영업이익률을 비교해줘.').coverage_complete
