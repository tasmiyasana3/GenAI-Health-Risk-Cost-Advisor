"""Simple PDF RAG: extract pages, retrieve relevant text, then ask Gemini."""
from pathlib import Path
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from langchain_core.prompts import PromptTemplate
from config import get_llm

RAG_PROMPT = PromptTemplate.from_template('''
Answer the question using only the PDF excerpts below.
If the answer is not present, say that the document does not provide enough information.
Do not invent policy terms or coverage decisions. Cite page numbers in your answer.

Excerpts:
{context}

Question: {question}
''')

def read_pdf(pdf_path):
    """Extract readable text and keep page numbers for citations."""
    if not pdf_path:
        raise ValueError('Upload a PDF before asking a question.')
    path = Path(pdf_path)
    if path.suffix.lower() != '.pdf':
        raise ValueError('Only PDF files are supported in this version.')
    reader = PdfReader(str(path))
    if len(reader.pages) > 100:
        raise ValueError('Please use a PDF with no more than 100 pages.')
    chunks = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = ' '.join((page.extract_text() or '').split())
        # Small overlapping passages work better than retrieving entire long pages.
        for start in range(0, len(text), 900):
            piece = text[start:start + 1100]
            if piece.strip():
                chunks.append({'page': page_number, 'text': piece})
    if not chunks:
        raise ValueError('No readable text found. Scanned PDFs need OCR, which is not included yet.')
    return chunks

def answer_document_question(pdf_path, question):
    """Retrieve matching passages and generate a document-grounded answer."""
    if not question or not question.strip():
        raise ValueError('Enter a question about the document.')
    chunks = read_pdf(pdf_path)
    # Starter retrieval uses TF-IDF. Semantic embeddings/vector DB can be added later.
    vectorizer = TfidfVectorizer(stop_words='english')
    matrix = vectorizer.fit_transform([chunk['text'] for chunk in chunks])
    query = vectorizer.transform([question])
    scores = cosine_similarity(query, matrix).ravel()
    top_indices = scores.argsort()[::-1][:4]
    if scores[top_indices[0]] <= 0:
        return 'I could not find relevant text in the uploaded document.'
    context = '\n\n'.join(
        f"[Page {chunks[i]['page']}] {chunks[i]['text']}"
        for i in top_indices if scores[i] > 0
    )
    # Ask Gemini to answer using the retrieved PDF passages.

    # Ask Gemini using the retrieved PDF passages.
    response = (RAG_PROMPT | get_llm()).invoke({
        'context': context,
        'question': question
    })

    # Extract only the readable text.
    content = response.content

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "\n".join(
            part["text"]
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )

    return str(content)