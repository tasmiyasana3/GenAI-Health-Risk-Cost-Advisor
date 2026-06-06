# GenAI-Health-Risk-Cost-Advisor

An end-to-end Machine Learning and Generative AI application focused on predicting healthcare insurance costs and providing personalized, data-backed client advisories.

### Live Application

[Click here to view the Interactive Dashboard](https://huggingface.co/spaces/TasmiyaSana23/ai-health-risk-and-cost-advisor)

---

## Project Overview

This project builds on my foundational [Health Insurance Cost Prediction project](https://github.com/tasmiyasana3/Health-Insurance-Cost-Prediction) by integrating Generative AI (Google Gemini API). It transforms raw predictive model outputs into human-readable, personalized client reports. This bridges the gap between statistical cost estimation and actionable business communication.

---

## Business Objective

* **Predictive Accuracy:** Estimate individual insurance costs using refined machine learning models.
* **GenAI Communication:** Change raw model predictions into professional, easy-to-understand client advisories.
* **Operational Efficiency:** Support data-driven premium pricing and proactive risk assessment.

---

## Dataset Information

* **Total Records:** 25,000 customer records
* **Features:** 24 variables (demographic, lifestyle, and medical history)
* **Target Variable:** `insurance_cost` (Continuous)

### Important Features

* Age, BMI, Weight, Smoking status, Exercise habits
* Cholesterol level, Glucose level, Doctor visits, Health checkups
* Medical history and Insurance tenure

---

## Tech Stack

* **Python**
* **ML Libraries:** Pandas, NumPy, Scikit-learn, XGBoost, SciPy
* **GenAI:** Google Gemini API
* **Deployment:** Gradio, Hugging Face Spaces

---

## Methodology & Evolution

I maintained the strong pipeline developed in my baseline project to ensure accuracy:

### 1. Data Pipeline

* **Preprocessing:** Handled missing values, corrected inconsistencies, and treated BMI outliers using the IQR/Winsorization method.
* **Feature Engineering:** Kept key engineered features: `ever_hospitalized`, `years_since_last_admission`, and `health_risk_score`.
* **Scaling:** Used `StandardScaler` for numeric features and One-hot encoding for categorical variables.

### 2. Machine Learning Model

* **Foundation:** Used the tuned `XGBoost Regressor` from my previous baseline study to ensure reliable cost predictions.

### 3. GenAI Integration

The pipeline now includes a "Communication Layer" that:

* Takes the regression model output.
* Processes inputs via the **Google Gemini API**.
* Generates a personalized advisory report explaining the risk drivers and offering lifestyle management recommendations.

---

## Repository Contents

* `app.py`: Deployment code for the Gradio interface and the Gemini API logic.
* `notebook.ipynb`: Full implementation, including EDA, model training, and the GenAI pipeline.
* `data.csv`: Health insurance dataset (25,000 records).
* `requirements.txt`: Project dependencies.

---

## Business Value

* **Transparency:** Helps customers understand the factors influencing their insurance premiums.
* **Fairness:** Provides data-driven explanations for risk assessments.
* **Proactive Health:** Uses GenAI to encourage better lifestyle management, potentially reducing long-term risk.

---

## Conclusion

This project shows how combining Machine Learning with Generative AI can create a more transparent and customer-focused insurance system. By identifying key risk factors and providing AI-driven, easy-to-understand explanations, this tool helps insurance companies improve premium pricing fairness, boost operational efficiency, and support better long-term health outcomes for clients.

---

## Author

**Tasmiya Sana**
