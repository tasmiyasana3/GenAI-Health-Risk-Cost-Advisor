"""Reusable, readable transformations shared by model training and inference.

Keep this file beside the notebook and available when loading the saved joblib model.
"""
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin


class InsuranceFeatureBuilder(BaseEstimator, TransformerMixin):
    """Create admission-history indicators without inventing missing admission years."""

    def fit(self, X, y=None):
        # No statistics are learned; transform is deterministic.
        return self

    def transform(self, X):
        X = X.copy()
        year = pd.to_numeric(X['Year_last_admitted'], errors='coerce')
        # 1 = a year is recorded; 0 = year is missing (not confirmed never admitted).
        X['admission_year_recorded'] = year.notna().astype(int)
        # Keep year information without a reference-year assumption.
        X['admission_year_category'] = year.map(
            lambda value: str(int(value)) if pd.notna(value) else 'Unknown'
        )
        # Experimental proxy, not a validated medical risk score.
        heart = pd.to_numeric(X['heart_decs_history'], errors='coerce')
        other = pd.to_numeric(X['other_major_decs_history'], errors='coerce')
        X['health_risk_score'] = heart + other + X['admission_year_recorded']
        return X


class SelectColumns(BaseEstimator, TransformerMixin):
    """Keep exactly the model's selected features in a reproducible order."""

    def __init__(self, columns):
        self.columns = columns

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return X.loc[:, self.columns].copy()


class IQRClipper(BaseEstimator, TransformerMixin):
    """Clip numeric inputs using IQR bounds fitted on training data only."""

    def __init__(self, factor=1.5):
        self.factor = factor

    def fit(self, X, y=None):
        values = np.asarray(X, dtype=float)
        q1 = np.nanpercentile(values, 25, axis=0)
        q3 = np.nanpercentile(values, 75, axis=0)
        iqr = q3 - q1
        self.lower_ = q1 - self.factor * iqr
        self.upper_ = q3 + self.factor * iqr
        return self

    def transform(self, X):
        return np.clip(np.asarray(X, dtype=float), self.lower_, self.upper_)
