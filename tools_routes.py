"""Routes for FinAssist's deterministic financial Tools.

Every calculation is performed here in Flask, never re-derived by the
AI — see SYSTEM.MD's "TOOL RESULTS" section and chat_routes.py's
tool_context handling. Routes stay thin: validation and formulas live
in `services/tools/<tool>/service.py` and `calculator.py`; a route only
parses the request, calls the service, and maps exceptions to the
existing structured error shape (utils.error_response).
"""
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from services.tools.affordability import service as affordability_service
from services.tools.currency import service as currency_service
from services.tools.currency.service import CurrencyProviderUnavailable
from services.tools.debt_payoff import service as debt_payoff_service
from services.tools.investment import service as investment_service
from services.tools.loan import service as loan_service
from services.tools.savings import service as savings_service
from services.tools.subscription_cost import service as subscription_cost_service
from services.tools.subscription_cost.service import SubscriptionNotFound
from utils import ValidationError, current_user_id, error_response, validation_error_response

tools_routes = Blueprint("tools", __name__)
logger = logging.getLogger(__name__)


@tools_routes.route("/api/tools/currency/currencies", methods=["GET"])
@jwt_required()
def get_currencies():
    return jsonify({"currencies": currency_service.list_currencies()}), 200


@tools_routes.route("/api/tools/currency/convert", methods=["POST"])
@jwt_required()
def post_currency_convert():
    data = request.get_json(silent=True) or {}
    try:
        result = currency_service.convert(data)
    except ValidationError as exc:
        return validation_error_response(exc)
    except CurrencyProviderUnavailable:
        return error_response(
            "CURRENCY_PROVIDER_UNAVAILABLE",
            "The exchange rate provider is temporarily unavailable. Please try again.",
            502,
        )
    except Exception:
        logger.exception("Currency conversion error")
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while converting currency.", 500
        )
    return jsonify(result), 200


@tools_routes.route("/api/tools/loan/calculate", methods=["POST"])
@jwt_required()
def post_loan_calculate():
    data = request.get_json(silent=True) or {}
    try:
        result = loan_service.calculate(data)
    except ValidationError as exc:
        return validation_error_response(exc)
    except Exception:
        logger.exception("Loan calculation error")
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while calculating the loan.", 500
        )
    return jsonify(result), 200


@tools_routes.route("/api/tools/savings/calculate", methods=["POST"])
@jwt_required()
def post_savings_calculate():
    data = request.get_json(silent=True) or {}
    try:
        result = savings_service.calculate(data)
    except ValidationError as exc:
        return validation_error_response(exc)
    except Exception:
        logger.exception("Savings calculation error")
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while calculating savings.", 500
        )
    return jsonify(result), 200


@tools_routes.route("/api/tools/affordability/calculate", methods=["POST"])
@jwt_required()
def post_affordability_calculate():
    data = request.get_json(silent=True) or {}
    try:
        result = affordability_service.calculate(data)
    except ValidationError as exc:
        return validation_error_response(exc)
    except Exception:
        logger.exception("Affordability calculation error")
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while calculating affordability.", 500
        )
    return jsonify(result), 200


@tools_routes.route("/api/tools/debt-payoff/calculate", methods=["POST"])
@jwt_required()
def post_debt_payoff_calculate():
    data = request.get_json(silent=True) or {}
    try:
        result = debt_payoff_service.calculate(data)
    except ValidationError as exc:
        return validation_error_response(exc)
    except Exception:
        logger.exception("Debt payoff calculation error")
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while calculating debt payoff.", 500
        )
    return jsonify(result), 200


@tools_routes.route("/api/tools/investment/calculate", methods=["POST"])
@jwt_required()
def post_investment_calculate():
    data = request.get_json(silent=True) or {}
    try:
        result = investment_service.calculate(data)
    except ValidationError as exc:
        return validation_error_response(exc)
    except Exception:
        logger.exception("Investment calculation error")
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while calculating investment growth.", 500
        )
    return jsonify(result), 200


@tools_routes.route("/api/tools/subscription-cost/calculate", methods=["POST"])
@jwt_required()
def post_subscription_cost_calculate():
    user_id = current_user_id()
    data = request.get_json(silent=True) or {}
    try:
        result = subscription_cost_service.calculate(user_id, data)
    except ValidationError as exc:
        return validation_error_response(exc)
    except SubscriptionNotFound as exc:
        return error_response(
            "SUBSCRIPTION_NOT_FOUND",
            "One or more subscription_ids were not found.",
            404,
            {"subscription_ids": exc.missing_ids},
        )
    except Exception:
        logger.exception("Subscription cost calculation error user_id=%s", user_id)
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while calculating subscription cost.", 500
        )
    return jsonify(result), 200
