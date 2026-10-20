
# services/ml_service.py

"""
Load the trained insurance cost model and generate predictions.

The model is trained separately in the ML notebook.
This file is only responsible for loading the saved pipeline
and using it to predict insurance costs.
"""

from pathlib import Path
from functools import lru_cache

import joblib
import pandas as pd

# Import the custom transformers used when the pipeline was trained.
# Joblib needs these classes to reconstruct the saved pipeline.
import insurance_transformers


# Get the project root from the location of this file.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Location of the model exported by the training notebook.
MODEL_PATH = PROJECT_ROOT / "models" / "insurance_pipeline.joblib"


# Raw inputs needed by the current feature builder and selected model.
# The admission-history features are created inside the saved pipeline.
REQUIRED_FIELDS = [
    "years_of_insurance_with_us",
    "regular_checkup_last_year",
    "adventure_sports",
    "visited_doctor_last_1_year",
    "age",
    "weight",
    "covered_by_any_other_company",
    "weight_change_in_last_one_year",
    "Year_last_admitted",
    "heart_decs_history",
    "other_major_decs_history",
]


@lru_cache(maxsize=1)
def load_model():
    """
    Load the saved model once and reuse it for later predictions.

    This avoids reading the Joblib file every time a user clicks
    the prediction button.
    """

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model file not found: {MODEL_PATH}\n"
            "Run the model export cell in the training notebook first."
        )

    try:
        # Load only model files created by a trusted source.
        model = joblib.load(MODEL_PATH)

        print(f"ML pipeline loaded from: {MODEL_PATH}")
        return model

    except Exception as error:
        raise RuntimeError(
            f"Unable to load the insurance model: {error}"
        ) from error


def predict_insurance_cost(customer_data: dict) -> float:
    """
    Predict insurance cost for one customer.

    customer_data: Dictionary containing the required raw inputs.
    Returns: Predicted insurance cost as a float.
    """

    # Check for missing fields before calling the model.
    missing_fields = [
        field for field in REQUIRED_FIELDS
        if field not in customer_data
    ]

    if missing_fields:
        raise ValueError(
            "Missing required inputs: " + ", ".join(missing_fields)
        )

    # Create one row using the expected input column names.
    input_data = pd.DataFrame([{
        field: customer_data[field]
        for field in REQUIRED_FIELDS
    }])

    try:
        # Feature engineering and preprocessing happen inside
        # the saved pipeline. They should not be repeated here.
        model = load_model()
        prediction = model.predict(input_data)

        return round(float(prediction[0]), 2)

    except Exception as error:
        raise RuntimeError(
            f"Insurance cost prediction failed: {error}"
        ) from error
