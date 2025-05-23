# email-agent-workflow/email_workflow_agent/subagents/classifier_agent/agent.py
from google.adk.agents import LlmAgent

# Use a defined model constant or string
GEMINI_MODEL = "gemini-2.0-flash"

# Define the Email Classifier Agent
classifier_agent = LlmAgent(
    name="EmailClassifierAgent",
    model=GEMINI_MODEL,
    # Instruction to classify email type based on subject and body (read from state)
    instruction="""You are an Email Classifier AI.
    Your task is to determine the type of the email provided in the session state
    based on the subject and body content.

    Read the email subject from state['email_subject'] and body from state['email_body'].

    Classify the email into one of these types:
    - "translation" if the subject indicates a request for translation (e.g., "Translation Request", "Please translate").
    - "review" if the subject indicates a request for reviewing a translation (e.g., "Request for Review", "Translation Check").
    - "other" for any other type of email.

    Output ONLY the classification type as a single word ("translation", "review", or "other").
    Do not add any explanations or other text.
    """,
    description="Classifies incoming email as 'translation', 'review', or 'other'.",
    output_key="email_type", # Save the classification result to state['email_type']
)