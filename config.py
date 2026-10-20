# ==============================================================================
# SECTION 1: INITIALIZE THE AI BRAIN
# The API key is stored in Hugging Face Secrets and is loaded automatically 
# when the application starts.
# ==============================================================================




# config.py
# Shared file paths and Gemini configuration.

import os
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI


# Locate the project folder.
PROJECT_ROOT = Path(__file__).resolve().parent

# Define paths used by the application.
DATA_PATH = PROJECT_ROOT / "data" / "Data.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "insurance_pipeline.joblib"

# Load API settings from the project's .env file.
load_dotenv(PROJECT_ROOT / ".env")


@lru_cache(maxsize=1)
def get_llm():
    """
    Initialize Gemini when the application needs it.

    The model is created once and reused for later requests.
    """

    # Read the API key from environment variables.
    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY is missing. "
            "Add it to the project's .env file."
        )

    # Read the Gemini model name from the same .env file.
    model_name = os.getenv("GEMINI_MODEL")

    if not model_name:
        raise ValueError(
            "GEMINI_MODEL is missing. "
            "Add a supported Gemini model name to .env."
        )

    # Initialize Gemini for advisory generation and RAG.
    return ChatGoogleGenerativeAI(
        model=model_name,
        temperature=0.3,
        api_key=api_key
    )


