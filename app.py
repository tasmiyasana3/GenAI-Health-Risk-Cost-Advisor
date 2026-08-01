# ==============================================================================
# INSURANCE COST & RISK ANALYTICS PRODUCTION CODE
# This script creates an interactive web dashboard using Gradio.
# It connects a machine learning database to a Google Gemini 3.5 AI model.
# The app takes a client's health metrics, calculates company averages,
# and automatically creates a data analysis report and a polished customer email.
# ==============================================================================

import os
import pandas as pd
import gradio as gr
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate


# ==============================================================================
# SECTION 1: INITIALIZE THE AI BRAIN
# The API key is stored in Hugging Face Secrets and is loaded automatically 
# when the application starts.
# ==============================================================================


# Initialize the Google Gemini 3.5 Flash
# A low temperature (0.3) keeps the AI responses more consistent and factual.

llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash",
    temperature=0.3
)


# ==============================================================================
# SECTION 2: CALCULATE COST & PROFILE BASELINES
# Read the dataset and calculate the company baseline values that
# will be used as reference points in the AI-generated report.
# ==============================================================================

print("Reading Data.csv file to calculate baseline averages...")

try:
    # Use the dataframe already loaded in memory if it exists.
    if "genai_df" in locals() or "genai_df" in globals():
        avg_cost_baseline = float(genai_df["insurance_cost"].mean())
        avg_steps_baseline = float(genai_df["daily_avg_steps"].mean())

    else:
        # Otherwise, read the dataset directly from the project folder.
        fallback_df = pd.read_csv("Data.csv")
        avg_cost_baseline = float(fallback_df["insurance_cost"].mean())
        avg_steps_baseline = float(fallback_df["daily_avg_steps"].mean())

except Exception as error_msg:
    # If the dataset cannot be loaded, use fallback values so the app can still run.
    print(
        "Notice: Could not read CSV file. "
        f"Using default values. Detail: {error_msg}"
    )

    avg_cost_baseline = 27147.41
    avg_steps_baseline = 5089.43


# Format the baseline values before inserting them into the prompt.
str_avg_cost = f"Rs. {avg_cost_baseline:,.2f}"
str_avg_steps = f"{avg_steps_baseline:,.0f}"

print("Corporate dataset baseline parameters loaded into pipeline memory:")
print(f" Company Average Cost Baseline: {str_avg_cost}")
print(f" Company Average Daily Steps Baseline: {str_avg_steps} steps")


# ==============================================================================
# SECTION 3: PROMPT ENGINEERING & TEMPLATE SETUP
# Prompt template used to generate the insurance risk assessment
# and customer communication.
# ==============================================================================

prompt_blueprint = """
You are acting as an Expert Insurance Underwriting Analytics Specialist. Your task is to review a customer's health and lifestyle attributes, evaluate their risks against our baseline averages, and generate a clear profile report.

Here are our historical company baselines for reference:
- Historical Baseline Average Premium Cost: {company_cost_avg}
- Historical Baseline Average Daily Steps: {company_steps_avg}

Customer Profile Data under review:
- Customer Name: {applicant_name}
- Current Age: {applicant_age}
- Professional Occupation: {applicant_occupation}
- Smoking Status: {applicant_smoking}
- Measured Body Mass Index (BMI): {applicant_bmi}
- Logged Daily Average Steps: {applicant_steps}
- Past History of Heart Disease: {applicant_heart_history}

Please structure your text output response precisely using these exact markdown headers:

### RISK ASSESSMENT
Analyze how this customer's traits compare directly to our company baselines. State clearly which specific parameters increase or decrease their risk profile (e.g., impact of smoking habits, weight deviations, or medical histories) using clean, non-technical logic.

<hr style="border: 0; border-top: 1px solid #ccc; margin: 15px 0;">

### CLIENT COMMUNICATION
Draft a highly polished, professional, and friendly notification email to the customer. The text must state their custom insurance premium quotation clearly, acknowledge positive habits (like hitting step metrics), and politely encourage specific lifestyle improvements where needed. Do not use or mention any internal department roles like recruiters or underwriters in the text.

Your complete underwriting report output:
"""


# Set up the LangChain layout object.
# Register all variables that will be passed into the prompt.
prompt_component = PromptTemplate(
    input_variables=[
        "company_cost_avg",
        "company_steps_avg",
        "applicant_name",
        "applicant_age",
        "applicant_occupation",
        "applicant_smoking",
        "applicant_bmi",
        "applicant_steps",
        "applicant_heart_history"
    ],
    template=prompt_blueprint
)


# Connect the prompt template to the Gemini model.
insurance_ai_pipeline = prompt_component | llm

print("LangChain processing architecture linked and ready to process inputs!")


# ==============================================================================
# SECTION 4: THE DATA EXECUTION LOGIC
# Executes when the Generate button is clicked.
# Collects the user inputs, runs the LangChain pipeline,
# and returns the generated report.
# ==============================================================================

def execute_dashboard_analysis(
    name,
    age,
    occupation,
    smoking,
    bmi,
    steps,
    heart_flag
):
    print("=== Generate button clicked ===")

    try:
        # Convert the checkbox value into a readable string for the prompt.
        heart_status_string = (
            "Yes, customer has a documented history of heart conditions"
            if heart_flag
            else "No documented history of heart disease"
        )

        print("Preparing customer profile data...")

        pipeline_inputs = {
            "company_cost_avg": str(str_avg_cost),
            "company_steps_avg": str(str_avg_steps),
            "applicant_name": str(name),
            "applicant_age": str(int(age)),
            "applicant_occupation": str(occupation),
            "applicant_smoking": str(smoking),
            "applicant_bmi": f"{float(bmi):.1f}",
            "applicant_steps": f"{int(steps):,}",
            "applicant_heart_history": heart_status_string
        }

        print("Calling Gemini API...")

        pipeline_result = insurance_ai_pipeline.invoke(pipeline_inputs)

        print("Gemini response received successfully.")

        content = pipeline_result.content

        # Handle both string and list-based Gemini responses.
        if isinstance(content, list):
            text_parts = []

            for part in content:
                if isinstance(part, str):
                    text_parts.append(part)

                elif isinstance(part, dict) and "text" in part:
                    text_parts.append(str(part["text"]))

            if text_parts:
                return "\n\n".join(text_parts)

        # Gradio Markdown requires a string
        # Always return a string for the Markdown component.
        return str(content)

    except Exception as error:
        import traceback

        print("========== GEMINI PIPELINE ERROR ==========")
        # Print the full error in the logs for debugging.
        print(traceback.format_exc()) 
        print("===========================================")

        return (
            "### Error generating report\n\n"
            f"```text\n{type(error).__name__}: {str(error)}\n```"
        )


# ==============================================================================
# SECTION 5: WEB VISUAL FRONTEND DESIGN (GRADIO UI)
# Build the Gradio dashboard layout.
# The left panel collects user inputs, while the right panel displays the AI report.
# ==============================================================================

with gr.Blocks() as insurance_dashboard_app:

    gr.Markdown(
        "<center><h1 style='color: #0F2942;'>"
        "INTELLIGENT INSURANCE COST & RISK ANALYTICS DASHBOARD"
        "</h1></center>"
    )

    gr.Markdown("---")

    gr.Markdown(
        "### *Quick Start:* Enter a client's health data on the left and click "
        "generate. The app will automatically read our company database to run "
        "a risk review and write up a tailored quote email."
    )

    # Add a separator between the header and the dashboard.
    gr.Markdown("---")

    with gr.Row():  # Creates a clear side-by-side row layout partitioning the screen

        # Left panel for entering customer information.
        with gr.Column(scale=1):

            gr.Markdown("<h3>Profile Configuration Inputs</h3>")

            ui_name = gr.Textbox(
                label="Customer Full Name",
                value="Alexander Wright"
            )

            ui_age = gr.Number(
                label="Current Age",
                value=42
            )

            ui_occupation = gr.Dropdown(
                choices=["Salaried", "Business", "Student"],
                label="Occupation Sector",
                value="Salaried"
            )

            ui_smoking = gr.Radio(
                choices=["never smoked", "smokes", "formerly smoked"],
                label="Smoking Status",
                value="smokes"
            )

            ui_bmi = gr.Slider(
                minimum=12.0,
                maximum=48.0,
                step=0.1,
                label="Body Mass Index (BMI)",
                value=29.2
            )

            ui_steps = gr.Slider(
                minimum=1000,
                maximum=16000,
                step=100,
                label="Daily Average Steps",
                value=3200
            )

            ui_heart = gr.Checkbox(
                label="Documented History of Heart Illness",
                value=False
            )

            submit_action_btn = gr.Button(
                "Generate AI Risk & Communication Report",
                variant="primary"
            )

        # Right panel for displaying the generated report.
        with gr.Column(scale=2):

            output_display = gr.Markdown(
                "### Automated Underwriting & Client Communication Report\n\n"
                "*The final risk analysis narrative and automated client email "
                "draft will appear here after clicking the button on the left.*"
            )

    # Connect the Generate button to the backend function.
    submit_action_btn.click(
        fn=execute_dashboard_analysis,
        inputs=[
            ui_name,
            ui_age,
            ui_occupation,
            ui_smoking,
            ui_bmi,
            ui_steps,
            ui_heart
        ],
        outputs=output_display
    )


# ==============================================================================
# SECTION 6: APPLICATION LAUNCH
# Hugging Face Spaces automatically provides the public application URL.
# The theme is passed to launch() for compatibility with Gradio 6.
# ==============================================================================

# Launch the Gradio application.

if __name__ == "__main__":
    insurance_dashboard_app.launch(
        theme=gr.themes.Soft(),
        show_error=True
    )
