      
# email-agent-workflow/email_workflow_agent/__init__.py
from .agent import root_agent

# You might need to import subagents here if the root_agent needs them
# directly in its __init__ for structure definition, although CustomAgent
# allows more flexibility in referencing instance attributes.
# For CustomAgent, importing in agent.py for the class definition is sufficient.
