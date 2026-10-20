
# services/advisory_service.py

"""
Generate an insurance cost advisory using Gemini.

The XGBoost model calculates the insurance cost separately.
This service receives that prediction and asks Gemini to
explain it in a customer-friendly report.
"""

from langchain_core.prompts import PromptTemplate

from config import get_llm
from services.data_service import get_company_baselines


# ==============================================================================
# STEP 1: DEFINE THE PROMPT TEMPLATE
# ==============================================================================

# This template tells Gemini what information it will receive,
# what it should explain, and how the final report should be structured.
#
# Values inside { } are placeholders. They will be replaced with
# actual customer information when the application runs.

PROMPT = PromptTemplate.from_template("""
You are writing a clear, professional insurance cost advisory
for a demonstration application.

Important instructions:
- The predicted cost comes from a trained machine learning model.
- It is an experimental estimate, not an official insurance quotation.
- Do not change the predicted amount or invent another premium.
- Do not claim that specific features caused the prediction.
- Do not diagnose medical conditions or guarantee insurance coverage.

Customer Profile:
- Name: {name}
- Age: {age}
- Weight: {weight} kg
- Predicted Insurance Cost: {predicted_cost}

Company Reference Statistics:
- Average Insurance Cost: {average_cost}
- Average Daily Steps: {average_steps}

Additional Customer Lifestyle Information:
(The following information is not necessarily used by the ML model.)

- Smoking Status: {smoking}
- Body Mass Index (BMI): {bmi}
- Daily Average Steps: {steps}
- Occupation: {occupation}

Generate the report using these exact Markdown headings:

### ESTIMATE SUMMARY

Explain the predicted insurance cost and compare it with
the historical dataset average.

Briefly discuss general lifestyle considerations where relevant,
but do not present them as explanations of the ML prediction.

### CUSTOMER EMAIL DRAFT

Write a short, professional, and friendly email to the customer.

Include:
- The customer's name.
- The predicted insurance cost.
- A brief explanation that this is an experimental estimate.
- A polite closing.

Do not describe the estimate as a confirmed insurance quotation.
""")


# ==============================================================================
# STEP 2: DEFINE THE ADVISORY GENERATION FUNCTION
# ==============================================================================

def generate_advisory(profile, predicted_cost):
    """
    Generate a customer advisory after the ML prediction is complete.

    Parameters:
        profile (dict):
            Customer information collected from the Gradio form.

        predicted_cost (float):
            Insurance cost calculated by the XGBoost model.

    Returns:
        str:
            Gemini-generated advisory in Markdown format.
    """

    # --------------------------------------------------------------------------
    # STEP 2.1: GET REFERENCE STATISTICS
    # --------------------------------------------------------------------------

    # Read historical averages calculated by data_service.py.
    # These values are used only for comparison in the advisory.
    average_cost, average_steps = get_company_baselines()


    # --------------------------------------------------------------------------
    # STEP 2.2: PREPARE THE PROMPT INPUTS
    # --------------------------------------------------------------------------

    # Match each placeholder in the prompt template with its value.
    #
    # profile["age"] is required, so it is accessed directly.
    # profile.get("smoking", "Not provided") is optional and
    # uses a fallback when the field is missing.

    inputs = {
        "name": profile.get("name", "Customer"),
        "age": profile["age"],
        "weight": profile["weight"],

        # The prediction is formatted to two decimal places.
        "predicted_cost": f"{predicted_cost:,.2f}",

        # Historical averages are also formatted for readability.
        "average_cost": f"{average_cost:,.2f}",
        "average_steps": f"{average_steps:,.0f}",

        # Additional information used for the written advisory.
        "smoking": profile.get("smoking", "Not provided"),
        "bmi": profile.get("bmi", "Not provided"),
        "steps": profile.get("steps", "Not provided"),
        "occupation": profile.get("occupation", "Not provided"),
    }


    # --------------------------------------------------------------------------
    # STEP 2.3: SEND THE PROMPT TO GEMINI
    # --------------------------------------------------------------------------

    # Get the configured Gemini model from config.py.
    # The model is initialized only when it is needed.
    llm = get_llm()

    # Connect the prompt template to Gemini using LangChain.
    advisory_chain = PROMPT | llm

    # Replace the prompt placeholders with customer data,
    # send the completed prompt to Gemini, and receive its response.
    response = advisory_chain.invoke(inputs)


    # --------------------------------------------------------------------------
    # STEP 2.4: CONVERT THE RESPONSE INTO TEXT
    # --------------------------------------------------------------------------

    # Gemini usually returns a string, but some responses
    # may contain multiple content blocks.
    #
    # Gradio Markdown expects text, so handle both formats.

    content = response.content

    # Case 1: Gemini returns a normal string.
    if isinstance(content, str):
        return content

    # Case 2: Gemini returns a list of content blocks.
    if isinstance(content, list):

        text_parts = []

        for part in content:

            # Add a text block directly.
            if isinstance(part, str):
                text_parts.append(part)

            # Extract text from dictionary-based content blocks.
            elif isinstance(part, dict) and "text" in part:
                text_parts.append(str(part["text"]))

        return "\n\n".join(text_parts)

    # Fallback for other response formats.
    return str(content)
