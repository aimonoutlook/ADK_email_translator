# email-agent-workflow/email_workflow_agent/subagents/reply_agent/agent.py
from google.adk.agents import LlmAgent

# Use a defined model constant or string
GEMINI_MODEL = "gemini-2.0-flash"

# Define the Initial Reply Agent
initial_reply_agent = LlmAgent(
    name="InitialReplyAgent",
    model=GEMINI_MODEL,
    # Instruction to generate the initial reply based on sender and email type (read from state)
    instruction="""You are an Email Auto-Responder.
    Your task is to generate a standardized initial reply based on the email type.

    Read the sender's email from state['email_sender_email'].
    Read the email type from state['email_type'].

    If the email type is "translation" or "review":
    Generate this exact reply:
    "Dear [Email Sender], We have received your email and we will be working on it. Kind regards, [Translator 1], [Translator 2]."
    Replace "[Email Sender]" with the actual email sender's address.
    Replace "[Translator 1]" and "[Translator 2]" with appropriate names (e.g., "AI Agent Team").

    If the email type is "other":
    Generate this exact reply:
    "Dear [Email Sender], We have received your email, but it does not appear to be a translation or review request. Please ensure the subject line is correct. Kind regards, AI Agent Team."
     Replace "[Email Sender]" with the actual email sender's address.


    Output ONLY the reply text. Do not add a subject line or any other text.
    """,
    description="Generates initial email reply text.",
    output_key="initial_reply_text", # Save the generated reply text to state
)