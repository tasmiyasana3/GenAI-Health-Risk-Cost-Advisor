"""Test input validation in the ML prediction service."""

import pytest
from services.ml_service import predict_insurance_cost


def test_missing_fields():
    # Provide incomplete customer information.
    customer = {"age": 30}

    # Check that the service rejects missing inputs.
    with pytest.raises(ValueError, match="Missing required inputs"):
        predict_insurance_cost(customer)