"""Routes for FinAssist's deterministic financial Tools.

Every calculation is performed here in Flask, never re-derived by the
AI — see SYSTEM.MD's "TOOL RESULTS" section and chat_routes.py's
tool_context handling. Routes stay thin: validation and conversion
logic live in `services/tools/currency/`; a route only
parses the request, calls the service, and maps exceptions to the
existing structured error shape (utils.error_response).
"""
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from services.tools.currency import service as currency_service
from services.tools.currency.service import CurrencyProviderUnavailable
from utils import ValidationError, error_response, validation_error_response

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
