# email-agent-workflow/email_workflow_agent/subagents/sender_agent/agent.py
from google.adk.agents import SequentialAgent
# Import specific tools used in this workflow branch
from ..tools.tools import send_email_tool

# Define the Sequential Workflow for Sending the Final Email
email_sender_agent = SequentialAgent(
    name="EmailSenderAgent",
    # Order: Prepare data, then send
    sub_agents=[
        # Minimal LlmAgent to orchestrate email sending tool
        LlmAgent(
             name="SendEmailOrchestrator",
             model="gemini-2.0-flash", # Minimal model
             instruction="Use the send_email_tool to send the final email. Get recipient from state['email_sender_email'], body from state['initial_reply_text'], and attachment artifact from state['translated_document_artifact'] or state['edited_document_artifact'] depending on email type.", # Instruction needs refinement to pick correct artifact based on type
             tools=[send_email_tool], # Provide the send email tool
             # output_key=None, # Don't save sender result to state typically
        ),
        # You could add a final confirmation agent here if needed
        LlmAgent(
             name="CompletionConfirmer",
             model="gemini-2.0-flash",
             instruction="Confirm to the user that the workflow is complete and the email has been sent.",
             # output_key=None,
        )
    ],
    description="Sends the final email with the processed document.",
)