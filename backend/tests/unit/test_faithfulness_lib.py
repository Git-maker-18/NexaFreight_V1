from nexafreight.eval.faithfulness import extract_numbers, normalize, is_grounded, faithfulness_rate

def test_extract_numbers():
    text = "The cost is $1,234.56, demurrage Rs 5,000, margin 50%, and base ETA is -10 days."
    assert extract_numbers(text) == [1234.56, 5000.0, 50.0, -10.0]

def test_extract_numbers_no_numbers():
    text = "There are no numbers here."
    assert extract_numbers(text) == []

def test_normalize():
    assert normalize(1234.56) == 1235.0
    assert normalize(0.00123456) == 0.001235
    assert normalize(0.0) == 0.0

def test_is_grounded_exact():
    assert is_grounded(1234.56, [10.0, 1234.56, 50.0])

def test_is_grounded_tolerance_pass():
    # 0.5% tolerance default
    # 1000 -> 0.5% is 5. So 1004 is within tolerance.
    assert is_grounded(1004.0, [1000.0])

def test_is_grounded_tolerance_fail():
    assert not is_grounded(1006.0, [1000.0])

def test_faithfulness_rate():
    answers = [
        {"answer": "The cost is $1,234.", "allowed_numbers": [1234.0, 500.0]},
        {"answer": "It is 50% chance.", "allowed_numbers": [10.0]}, # fail
        {"answer": "No numbers here.", "allowed_numbers": []} # pass
    ]
    res = faithfulness_rate(answers)
    assert res["passed"] == 2
    assert res["total"] == 3
    assert res["rate"] == 2.0 / 3.0
    assert not res["details"][1]["pass"]
