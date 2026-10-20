# ==============================================================================
# INSURANCE COST & RISK ANALYTICS PRODUCTION CODE
# This script creates an interactive web dashboard using Gradio.
# It connects a machine learning database to a Google Gemini 3.6 AI model.
# The app takes a client's health metrics, calculates company averages,
# and automatically creates a data analysis report and a polished customer email.
# ==============================================================================


"""Gradio interface for insurance cost prediction and PDF questions."""
import logging
import gradio as gr

# Import the backend function from advisory_service.py
from services.ml_service import predict_insurance_cost
from services.advisory_service import generate_advisory
from services.rag_service import answer_document_question

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_prediction(name, age, weight, tenure, checkup, adventure, visits,
                   other_cover, weight_change, admission_year, heart, other_disease,
                   occupation, smoking, bmi, steps):
    try:
        # Missing admission year stays missing; it does not mean 'never admitted'.
        year = None if admission_year is None or str(admission_year).strip() == '' else int(admission_year)
        profile = {
            'name': name, 'age': int(age), 'weight': float(weight),
            'years_of_insurance_with_us': int(tenure),
            'regular_checkup_last_year': int(checkup),
            'adventure_sports': int(adventure),
            'visited_doctor_last_1_year': int(visits),
            'covered_by_any_other_company': other_cover,
            'weight_change_in_last_one_year': float(weight_change),
            'Year_last_admitted': year,
            'heart_decs_history': int(heart),
            'other_major_decs_history': int(other_disease),
            'occupation': occupation, 'smoking': smoking,
            'bmi': bmi, 'steps': steps,
        }
        if profile['age'] < 0 or profile['weight'] <= 0 or profile['years_of_insurance_with_us'] < 0:
            raise ValueError('Please enter valid age, weight and insurance tenure.')
        predicted_cost = predict_insurance_cost(profile)
        summary = f'### Estimated insurance cost: {predicted_cost:,.2f}\n\n*Experimental ML estimate, not an official quotation.*'
        try:
            advisory = generate_advisory(profile, predicted_cost)
        except Exception:
            logger.exception('Gemini advisory failed; ML prediction succeeded.')
            advisory = 'The ML prediction succeeded, but the Gemini advisory could not be generated. Check the terminal log.'
        return summary, advisory
    except Exception as error:
        logger.exception('Prediction failed')
        return f'**Prediction error:** {error}', ''

def run_rag(pdf_path, question):
    try:
        return answer_document_question(pdf_path, question)
    except Exception as error:
        logger.exception('Document question failed')
        return f'**Document error:** {error}'

# ==============================================================================
# WEB VISUAL FRONTEND DESIGN (GRADIO UI)
# Build the Gradio dashboard layout.
# The left panel collects user inputs, while the right panel displays the AI report.
# ==============================================================================

with gr.Blocks(title='Insurance Cost & Document Advisor') as dashboard:
    gr.Markdown('# Insurance Cost & Document Advisor')
    gr.Markdown('Experimental portfolio app. Predictions are not insurance quotations or medical advice.')
    with gr.Tab('Cost prediction'):
        with gr.Row():
            with gr.Column():
                name = gr.Textbox(label='Customer name', value='Alexander Wright')
                age = gr.Number(label='Age', value=42, precision=0)
                weight = gr.Number(label='Weight (kg)', value=75)
                tenure = gr.Number(label='Years insured with us', value=3, precision=0)
                checkup = gr.Radio([0, 1], label='Regular checkup last year (0=No, 1=Yes)', value=1)
                adventure = gr.Radio([0, 1], label='Adventure sports (0=No, 1=Yes)', value=0)
                visits = gr.Number(label='Doctor visits in last year', value=2, precision=0)
                other_cover = gr.Radio(['Y', 'N'], label='Covered by another company?', value='N')
                weight_change = gr.Number(label='Weight change in last year (kg)', value=0)
                admission_year = gr.Textbox(label='Last admission year (leave blank if unknown)', value='')
                heart = gr.Radio([0, 1], label='Heart disease history (0=No, 1=Yes)', value=0)
                other_disease = gr.Radio([0, 1], label='Other major disease history (0=No, 1=Yes)', value=0)
                gr.Markdown('**Additional context for Gemini only (not selected XGBoost predictors):**')
                occupation = gr.Dropdown(['Salaried', 'Business', 'Student'], label='Occupation', value='Salaried')
                smoking = gr.Dropdown(['never smoked', 'smokes', 'formerly smoked'], label='Smoking', value='never smoked')
                bmi = gr.Number(label='BMI', value=25)
                steps = gr.Number(label='Daily steps', value=5000, precision=0)
                submit = gr.Button('Estimate cost and explain', variant='primary')
            with gr.Column():
                estimate_output = gr.Markdown()
                advisory_output = gr.Markdown()
        submit.click(run_prediction, inputs=[name, age, weight, tenure, checkup, adventure,
                    visits, other_cover, weight_change, admission_year, heart, other_disease,
                    occupation, smoking, bmi, steps], outputs=[estimate_output, advisory_output])
    with gr.Tab('Ask an insurance PDF'):
        pdf = gr.File(label='Upload PDF', file_types=['.pdf'], type='filepath')
        question = gr.Textbox(label='Question about the document')
        answer = gr.Markdown()
        gr.Button('Ask document').click(run_rag, inputs=[pdf, question], outputs=answer)

# ==============================================================================
# SECTION 6: APPLICATION LAUNCH
# Hugging Face Spaces automatically provides the public application URL.
# The theme is passed to launch() for compatibility with Gradio 6.
# ==============================================================================

# Launch the Gradio application.

if __name__ == '__main__':
    dashboard.launch(show_error=True)
