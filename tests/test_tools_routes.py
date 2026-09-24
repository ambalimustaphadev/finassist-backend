"""Route-level contract for the Tools blueprint: the Currency Converter
is the only Tool exposed over HTTP. The six calculators that used to
live here were removed and must stay gone."""
import pytest

REMOVED_CALCULATOR_PATHS = [
    "/api/tools/loan/calculate",
    "/api/tools/savings/calculate",
    "/api/tools/affordability/calculate",
    "/api/tools/debt-payoff/calculate",
    "/api/tools/investment/calculate",
    "/api/tools/subscription-cost/calculate",
]


@pytest.mark.parametrize("path", REMOVED_CALCULATOR_PATHS)
def test_removed_calculator_endpoints_return_404(client, auth_headers, path):
    response = client.post(path, headers=auth_headers, json={})
    assert response.status_code == 404


def test_only_currency_converter_routes_are_exposed_under_tools(app):
    tool_routes = {
        (rule.rule, method)
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/api/tools/")
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }
    assert tool_routes == {
        ("/api/tools/currency/currencies", "GET"),
        ("/api/tools/currency/convert", "POST"),
    }
