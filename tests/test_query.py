from lrai import query as q

QUERY = '("citation network" OR "citation graph") AND (forecast* OR predict*) NOT survey'


def test_openalex_rendering_drops_wildcards():
    assert q.to_openalex(QUERY) == '("citation network" OR "citation graph") AND (forecast OR predict) AND NOT survey'


def test_semantic_scholar_rendering_uses_symbols():
    assert q.to_semantic_scholar(QUERY) == '("citation network" | "citation graph") + (forecast* | predict*) -survey'


def test_arxiv_rendering_prefixes_fields_and_uses_andnot():
    assert q.to_arxiv(QUERY) == ('(all:"citation network" OR all:"citation graph") AND (all:forecast OR all:predict) '
                                 'ANDNOT all:survey')


def test_arxiv_passes_native_syntax_through():
    assert q.to_arxiv('ti:"graph" AND cat:cs.LG') == 'ti:"graph" AND cat:cs.LG'


def test_implicit_and_between_adjacent_terms():
    assert q.to_openalex('graph "neural network"') == 'graph AND "neural network"'


def test_negated_group_in_semantic_scholar():
    assert q.to_semantic_scholar("graph NOT (survey OR review)") == "graph -(survey | review)"


def test_plain_flattening_drops_negated_parts():
    assert q.to_plain(QUERY) == "citation network citation graph forecast predict"
    assert q.to_plain("a NOT (b OR c) d") == "a d"


def test_lowercase_operators_are_terms():
    assert q.to_openalex("graph and network") == "graph AND and AND network"
