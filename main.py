import asyncio
import os
import uuid
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.genai import types
from email_workflow_agent.agent import root_agent # Import the custom orchestrator agent

# Load environment variables from .env file
load_dotenv()

# --- Services ---
# Using in-memory services for simplicity. Replace with persistent options for production.
session_service = InMemorySessionService()
artifact_service = InMemoryArtifactService()

# --- Agent Runner Setup ---
APP_NAME = "email_translation_workflow"
# In a real app, USER_ID might come from an authenticated user session
# or be derived from the email sender. Using a fixed one for demo.
USER_ID = "email_sender_user" # Example user ID

runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
    artifact_service=artifact_service, # Provide artifact service
)

# --- Simulate Receiving an Email and Running Workflow ---

async def run_email_workflow(sender_email: str, subject: str, body: str, attachments: list):
    """Simulates receiving an email and triggering the ADK workflow."""
    session_id = str(uuid.uuid4()) # Unique session ID per email

    # Initial state to pass email details to the workflow
    initial_state = {
        "email_sender_email": sender_email,
        "email_subject": subject,
        "email_body": body,
        # Attachments could be passed as a list of dicts:
        # [{"filename": "report.docx", "bytes": b"...", "mime_type": "..."}]
        # Or as temp file paths after initial download outside ADK
        "initial_attachments": attachments # Passing simplified list of filenames for demo
        # In a real scenario, you'd handle byte data or temp paths here
    }

    # Create a new session for this email
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
        state=initial_state,
    )

    print(f"--- Starting workflow for email from {sender_email} (Session ID: {session_id[:8]}) ---")
    print(f"Subject: {subject}\n")

    # Provide the email body as the user's initial input to the agent
    # The agent's instruction will guide it to read subject/attachments from state
    user_message = types.Content(role="user", parts=[types.Part(text=body)])

    final_response_text = "Workflow completed."

    try:
        # Run the agent asynchronously
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=user_message, # Pass the email body as the initial user message
        ):
            # Log events for debugging
            # print(f"  Event: {event.author} - Type: {type(event).__name__} - Final: {event.is_final_response()}")
            # if event.content and event.content.parts:
            #      print(f"    Content: {str(event.content.parts[0].text)[:100]}...")
            # if event.actions:
            #      print(f"    Actions: {event.actions}")

            if event.is_final_response():
                if event.content and event.content.parts:
                     final_response_text = event.content.parts[0].text
                     print(f"--- Workflow Step Output ({event.author}): ---\n{final_response_text}\n")
                elif event.actions and event.actions.transfer_to_agent:
                     print(f"--- Workflow Decision: Transfer to {event.actions.transfer_to_agent} ---")
                else:
                     print("--- Workflow Step Output (Non-text final event) ---")


    except Exception as e:
        print(f"\n!!! Workflow encountered an ERROR: {e} !!!")
        import traceback
        traceback.print_exc()

    print(f"\n--- Workflow finished for Session ID: {session_id[:8]} ---")

# --- Example Usage ---
async def main():
    # Simulate two incoming emails
    await run_email_workflow(
        sender_email="translator1@example.com",
        subject="Translation Request for Q3 Report",
        body="Hi team, please translate the attached Q3 report (report_q3_en.docx) from English to French.",
        attachments=["report_q3_en.docx"] # Simplified attachment representation
    )

    print("\n" + "="*50 + "\n")

    await run_email_workflow(
        sender_email="officer2@example.com",
        subject="Request for Review the Translation (Policy Manual)",
        body="Hello team, please review the translation of the policy manual (policy_manual_fr.docx) against the English original (policy_manual_en.docx).",
        attachments=["policy_manual_fr.docx", "policy_manual_en.docx"] # Simplified attachment representation
    )

if __name__ == "__main__":
    # Use asyncio.run() for top-level execution in a script
    try:
        asyncio.run(main())
    except RuntimeError as e:
        # Handle the case where this is run in an already-running event loop (like some notebooks)
        if "cannot be called from a running event loop" in str(e):
            print("Info: Cannot run asyncio.run from a running event loop (e.g., Jupyter/Colab).")
            print("If in Jupyter/Colab, run 'await main()' in a cell instead.")
        else:
            raise e