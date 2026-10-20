
# services/data_service.py

"""
Read the insurance dataset and calculate reference statistics.

These averages are used by Gemini to compare a customer's
predicted insurance cost with the historical dataset.

This file does not train the ML model or generate predictions.
"""

import pandas as pd

from config import DATA_PATH


def get_company_baselines():
    """
    Calculate average insurance cost and average daily steps.

    Returns:
        tuple:
            (average_insurance_cost, average_daily_steps)

            Both values are returned as floats.
    """

    # STEP 1: Check whether the dataset exists.
    # DATA_PATH is defined in config.py and points to data/Data.csv.
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATA_PATH}\n"
            "Check that Data.csv is inside the data folder."
        )

    # STEP 2: Read only the columns needed for baseline calculations.
    # This avoids loading unnecessary columns into memory.
    try:
        df = pd.read_csv(
            DATA_PATH,
            usecols=["insurance_cost", "daily_avg_steps"]
        )

    except Exception as error:
        raise RuntimeError(
            f"Unable to read baseline data: {error}"
        ) from error

    # STEP 3: Calculate the historical averages.
    # mean() ignores missing numeric values by default.
    average_cost = float(df["insurance_cost"].mean())
    average_steps = float(df["daily_avg_steps"].mean())

    # STEP 4: Check that valid averages were calculated.
    # An empty column or a column containing only missing values
    # would produce NaN instead of a meaningful average.
    if pd.isna(average_cost) or pd.isna(average_steps):
        raise ValueError(
            "Unable to calculate company baselines. "
            "Check the insurance_cost and daily_avg_steps columns."
        )

    # STEP 5: Print the values to help with local debugging.
    print("Company baseline statistics loaded:")
    print(f"Average insurance cost: Rs. {average_cost:,.2f}")
    print(f"Average daily steps: {average_steps:,.0f}")

    # STEP 6: Return numeric values.
    # advisory_service.py will format these numbers for Gemini.
    return average_cost, average_steps
