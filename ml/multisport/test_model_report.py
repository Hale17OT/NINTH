from ml.multisport.model_report import decision


def test_decision_requires_both_predictive_and_betting_stability_for_use():
    metrics = {"samples": 600, "brier": .21}
    seasons = {
        "2024": {"brier": .20, "closing_line_betting": {"roi": .04}},
        "2025": {"brier": .22, "closing_line_betting": {"roi": -.03}},
    }
    assert decision(metrics, seasons, {})[0] == "LIMITED"
    seasons["2025"]["closing_line_betting"]["roi"] = .01
    assert decision(metrics, seasons, {})[0] == "USE"


def test_decision_rejects_probability_model_that_fails_brier_baseline():
    assert decision({"samples": 1000, "brier": .251}, {}, {})[0] == "REJECT"
