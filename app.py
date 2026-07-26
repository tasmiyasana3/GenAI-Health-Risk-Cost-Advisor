# ==============================================================================
# INSURANCE COST & RISK ANALYTICS PRODUCTION CODE
# This script creates an interactive web dashboard using Gradio. 
# It connects a machine learning database to a Google Gemini 2.5 AI model.
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
# The system automatically pulls the GOOGLE_API_KEY from Hugging Face Secrets.
# This ensures a seamless, zero-login, instant runtime view for the business user.
# ==============================================================================

# Start Google Gemini 2.5 Flash using the required 'models/' server path prefix.
# We set the temperature low to 0.3 so the AI stays factual and never guesses numbers.
llm = ChatGoogleGenerativeAI(
    model="models/gemini-2.5-flash",
    temperature=0.3
)

# ==============================================================================
# SECTION 2: CALCULATE REVENUE & PROFILE BASELINES
# We open our 'Data.csv' file to extract statistical averages from our dataset.
# The AI must know these true company benchmarks to evaluate new clients accurately.
# ==============================================================================
print("Reading Data.csv file to calculate baseline averages...")

try:
    # Check if our main data table is already sitting active in the system RAM
    if 'genai_df' in locals() or 'genai_df' in globals(): 
        avg_cost_baseline = float(genai_df['insurance_cost'].mean())
        avg_steps_baseline = float(genai_df['daily_avg_steps'].mean())
    else:
        # If RAM is blank, open the physical file saved in our cloud repository folder
        fallback_df = pd.read_csv('Data.csv')
        avg_cost_baseline = float(fallback_df['insurance_cost'].mean())
        avg_steps_baseline = float(fallback_df['daily_avg_steps'].mean())

except Exception as error_msg:
    # If both files disappear, load these verified defaults so the system never crashes
    print(f"Notice: Could not read CSV file. Using default values. Detail: {error_msg}")
    avg_cost_baseline = 27147.41
    avg_steps_baseline = 5089.43

# Format the numbers nicely into text (add currency, commas, and clear decimal spaces)
str_avg_cost = f"Rs. {avg_cost_baseline:,.2f}"
str_avg_steps = f"{avg_steps_baseline:,.0f}"

print("Corporate dataset baseline parameters loaded into pipeline memory:")
print(f" Company Average Cost Baseline: {str_avg_cost}")
print(f" Company Average Daily Steps Baseline: {str_avg_steps} steps")

# ==============================================================================
# SECTION 3: PROMPT ENGINEERING & TEMPLATE SETUP
# This is a master blueprint that forces the AI to act like an industry specialist
# and maps all our user form details straight into structured document fields.
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


# Set up the LangChain layout object and register all the input data keys we expect to receive
prompt_component = PromptTemplate(
    input_variables=[
        "company_cost_avg", "company_steps_avg", "applicant_name", "applicant_age", 
        "applicant_occupation", "applicant_smoking", "applicant_bmi", "applicant_steps", "applicant_heart_history"
    ],
    template=prompt_blueprint
)

# Pipe the prompt blueprint directly into our Gemini AI model using LangChain syntax
insurance_ai_pipeline = prompt_component | llm

print("LangChain processing architecture linked and ready to process inputs!")

# ==============================================================================
# SECTION 4: THE DATA EXECUTION LOGIC
# This function wakes up whenever a user clicks the button on the screen.
# It packages all user sliders and text parameters, passes them through the AI, 
# and returns the final clean written content directly to the webpage window.
# ==============================================================================
def execute_dashboard_analysis(name, age, occupation, smoking, bmi, steps, heart_flag):
    # Convert the raw True/False checkbox value into a simple plain text string for the AI prompt
    heart_status_string = "Yes, customer has a documented history of heart conditions" if heart_flag else "No documented history of heart disease"
    
    # Run the input data directly through our active LangChain pipeline map
    pipeline_result = insurance_ai_pipeline.invoke({
        "company_cost_avg": str(str_avg_cost),
        "company_steps_avg": str(str_avg_steps),
        "applicant_name": str(name),
        "applicant_age": str(int(age)),
        "applicant_occupation": str(occupation),
        "applicant_smoking": str(smoking),
        "applicant_bmi": f"{float(bmi):.1f}",
        "applicant_steps": f"{int(steps):,}",
        "applicant_heart_history": heart_status_string
    })
    
    # Extract the core string text content and send it back to the frontend display box
    return pipeline_result.content

# ==============================================================================
# SECTION 5: WEB VISUAL FRONTEND DESIGN (GRADIO UI)
# This design lays out the buttons, checkboxes, sliders, and text display boxes.
# The scale argument controls width ratio. Column 1 (narrower), Column 2 (wider).
# ==============================================================================
with gr.Blocks(theme=gr.themes.Soft()) as insurance_dashboard_app:
    
    gr.Markdown("<center><h1 style='color: #0F2942;'> INTELLIGENT INSURANCE COST & RISK ANALYTICS DASHBOARD</h1></center>")
    gr.Markdown("---")
    gr.Markdown("### *Quick Start:* Enter a client's health data on the left and click generate. The app will automatically read our company database to run a risk review and write up a tailored quote email.")

# Adding a visual separator and extra vertical space
    gr.Markdown("---")
    
    with gr.Row(): # Creates a clear side-by-side row layout partitioning the screen
        
        # LEFT PANEL: The data entry form where the business staff inputs customer details
        with gr.Column(scale=1): 
            gr.Markdown("<h3>Profile Configuration Inputs</h3>")
            
            ui_name = gr.Textbox(label="Customer Full Name", value="Alexander Wright")
            ui_age = gr.Number(label="Current Age", value=42)
            ui_occupation = gr.Dropdown(choices=["Salaried", "Business", "Student"], label="Occupation Sector", value="Salaried")
            ui_smoking = gr.Radio(choices=["never smoked", "smokes", "formerly smoked"], label="Smoking Status", value="smokes")
            ui_bmi = gr.Slider(minimum=12.0, maximum=48.0, step=0.1, label="Body Mass Index (BMI)", value=29.2)
            ui_steps = gr.Slider(minimum=1000, maximum=16000, step=100, label="Daily Average Steps", value=3200)
            ui_heart = gr.Checkbox(label="Documented History of Heart Illness", value=False)
            
            submit_action_btn = gr.Button(" Generate AI Risk & Communication Report", variant="primary")
            
        # RIGHT PANEL: The display window where the text report renders cleanly
        with gr.Column(scale=2): 
            output_display = gr.Markdown(
                "### Automated Underwriting & Client Communication Report\n\n"
                "*The final risk analysis narrative and automated client email draft will appear here after clicking the button on the left.*"
            )
            
    # Instruct the web button to execute our Section 4 backend function on click
    submit_action_btn.click(
        fn=execute_dashboard_analysis,
        inputs=[ui_name, ui_age, ui_occupation, ui_smoking, ui_bmi, ui_steps, ui_heart],
        outputs=output_display
    )

# Boot up the server application. This launch method works perfectly on Hugging Face Spaces cloud nodes.
if __name__ == "__main__":
    insurance_dashboard_app.launch()

