from score_results import numeric_ok, route_ok

def test_numeric_requires_all_values_and_units():
    t={'numeric_gold':{'a':3,'b':5},'tolerance':.01}
    assert numeric_ok(t,{'numeric_outputs':{'a':3.009,'b':5},'units_correct':True})
    assert not numeric_ok(t,{'numeric_outputs':{'a':3},'units_correct':True})
    assert not numeric_ok(t,{'numeric_outputs':{'a':3,'b':5},'units_correct':False})
    assert not numeric_ok(t,{'numeric_outputs':{'a':True,'b':5},'units_correct':True})

def test_non_numeric_not_zero():
    assert numeric_ok({'numeric_gold':None},{}) is None

def test_direct_cannot_start_with_retrieval():
    t={'category':'direct_calculation'}
    assert route_ok(t,{'action_history':[{'action_type':'calculate'},{'action_type':'verify'}]})
    assert not route_ok(t,{'action_history':[{'action_type':'retrieve'},{'action_type':'calculate'}]})

def test_kb_must_retrieve_before_calculating():
    t={'category':'kb_formula'}
    assert route_ok(t,{'action_history':[{'action_type':'retrieve'},{'action_type':'calculate'}]})
    assert not route_ok(t,{'action_history':[{'action_type':'calculate'},{'action_type':'retrieve'}]})

def test_missing_calculation_does_not_pass_route():
    assert not route_ok({'category':'kb_formula'},{'action_history':[{'action_type':'retrieve'},{'action_type':'stop'}]})
