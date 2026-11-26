from app import unit_validation


def test_cell_membership_discards_impossible_centers_before_overlap(monkeypatch):
    table = {'cells': [{'bbox':[i*10, 0, i*10+9, 10]} for i in range(200)]}
    calls = []
    original = unit_validation.overlap
    def measured(a, b):
        calls.append(1)
        return original(a, b)
    monkeypatch.setattr(unit_validation, 'overlap', measured)
    assert unit_validation._cells({'source':'native', 'bbox':[1,1,8,8]}, table) == [table['cells'][0]]
    assert len(calls) == 1


def test_request_cache_cannot_reuse_mutated_source_or_cross_requests():
    from app.verification_cache import verification_request, memoized, fingerprint
    source = {'document':'doc-a', 'revision':'r1', 'source_hash':'a', 'cells':[1]}
    calls = []
    def verify():
        calls.append(1)
        return list(source['cells'])
    with verification_request():
        assert memoized('test', fingerprint(source), verify) == [1]
        result = memoized('test', fingerprint(source), verify)
        result.append(9)
        assert memoized('test', fingerprint(source), verify) == [1]
        source['cells'] = [2]
        assert memoized('test', fingerprint(source), verify) == [2]
    with verification_request():
        assert memoized('test', fingerprint(source), verify) == [2]
    assert len(calls) == 3


def _stored_page(text='본문'):
    import hashlib
    from types import SimpleNamespace as NS
    return NS(id='page-1', document_id='doc-1', page_number=1, final_text=text,
        extraction=NS(parser_version='legacy-1', final_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                      provenance={'selected_words': []}, table_facts=[]))


def test_page_fingerprint_is_computed_once_per_request_for_identical_objects(monkeypatch):
    from app import extraction_provenance, verification_cache
    from app.verification_cache import verification_request
    hashed, verified = [], []
    original = verification_cache.fingerprint
    monkeypatch.setattr(verification_cache, 'fingerprint', lambda value: hashed.append(1) or original(value))
    monkeypatch.setattr(extraction_provenance, '_validated_stored_facts',
                        lambda page, unit_audit=None: verified.append(1) or [])
    page = _stored_page()
    with verification_request():
        for _ in range(3):
            assert extraction_provenance.validated_stored_facts(page) == []
        assert (len(hashed), len(verified)) == (1, 1)
    with verification_request():
        extraction_provenance.validated_stored_facts(page)
    assert (len(hashed), len(verified)) == (2, 2)


def test_page_fingerprint_is_recomputed_when_page_inputs_are_replaced_or_resized(monkeypatch):
    import hashlib
    from app import extraction_provenance, verification_cache
    from app.verification_cache import verification_request
    hashed = []
    original = verification_cache.fingerprint
    monkeypatch.setattr(verification_cache, 'fingerprint', lambda value: hashed.append(1) or original(value))
    monkeypatch.setattr(extraction_provenance, '_validated_stored_facts', lambda page, unit_audit=None: [])
    page = _stored_page()
    with verification_request():
        extraction_provenance.validated_stored_facts(page)
        page.final_text = '바뀐 본문'
        page.extraction.final_text_sha256 = hashlib.sha256(page.final_text.encode()).hexdigest()
        extraction_provenance.validated_stored_facts(page)
        assert len(hashed) == 2
        page.extraction.table_facts = []
        extraction_provenance.validated_stored_facts(page)
        assert len(hashed) == 3
        page.extraction.provenance['unsafe_spans'] = []
        extraction_provenance.validated_stored_facts(page)
        assert len(hashed) == 4
        page.extraction.table_facts.append({'metric': 'x'})
        extraction_provenance.validated_stored_facts(page)
        assert len(hashed) == 5
        extraction_provenance.validated_stored_facts(_stored_page())
        assert len(hashed) == 6
