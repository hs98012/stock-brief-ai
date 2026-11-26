from app.evidence_facts import economic_facts


def test_repeated_cross_page_fact_has_one_identity_but_different_values_do_not():
    from app.analysis_service import _fact_identity
    def candidate(quote, page):
        return {'quote':quote, 'facts':economic_facts(quote), 'page_number':page,
                'quality_status':'valid', 'analysis_perspective':'positive',
                'char_start':0, 'char_end':len(quote),
                'temporal_context':{'period_mentions':[{'text':'2Q26'}]}}
    a=candidate('2Q26 영업이익은 5,330억원으로 92.5% 증가했다.',1)
    b=candidate('2Q26 영업이익은 5,330억원으로 92.5% 증가했다. 추가 문맥입니다.',3)
    c=candidate('2Q26 영업이익은 6,330억원으로 92.5% 증가했다.',3)
    assert _fact_identity(a,'positive') == _fact_identity(b,'positive')
    assert _fact_identity(a,'positive') != _fact_identity(c,'positive')


def test_leading_particle_is_not_a_subject_label():
    facts=economic_facts('수익은 1,805억원(+7%)으로 전자·이노텍 매출 증가를 반영했다.')
    from app.evidence_facts import fact_title
    assert all(not (fact_title(f) or '').startswith('으로 ') for f in facts)
