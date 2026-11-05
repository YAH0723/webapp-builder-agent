"""Retry model proposals when parsing or consuming their returned records fails."""

import json

from infrastructure.shared.agent.discovery import DISCOVERY_RULES, DiscoverySession
from infrastructure.shared.project.git import checkpoint
from infrastructure.shared.agent.efficiency import enabled, positive_setting
from infrastructure.shared.agent.model_policy import ContextBudgetExceeded, task_call


RESPONSE_ERRORS = (ValueError, KeyError, TypeError, AttributeError, IndexError)
REPAIR_INSTRUCTIONS = """The previous proposal was rejected. Read correction.error and correction.details
in the input and fix that failure. correction.previous_response is the rejected
answer, not an accepted example. Return a complete replacement JSON object in the
original output format, including every required top-level section. Do not return
only the unchanged portion, a partial patch, or the correction metadata itself.
DSML/XML tool-call text is forbidden. If requesting context, return the allowed
context_request JSON object directly, never invoke/parameter tags. Otherwise return
the complete stage result. invalid_response is rejected data; never copy its format."""


def response_feedback(error, response):
    """Describe an actual response-consumption failure, without adding design rules."""
    message = str(error)
    if isinstance(error, KeyError):
        key = error.args[0] if error.args else "(unknown)"
        message = f"Missing key {key!r} while reading the model response. Return the requested complete records."
    if isinstance(error, json.JSONDecodeError):
        message += (" Output must be one valid JSON object, without DSML/XML tool-call tags, "
            "Markdown or text outside the object. For an allowed context query return "
            '{"context_request":{"kind":"<advertised kind>","query":"<needed fact>"}}. '
            "Otherwise return the stage result as JSON. Do not repeat the rejected format.")
    feedback = {"error": message, "error_type": type(error).__name__, "previous_response": response}
    if isinstance(error, json.JSONDecodeError):
        feedback["invalid_response"] = error.doc
    if hasattr(error, "feedback"):
        feedback["details"] = error.feedback
    return feedback


def propose_json(model, instructions, request, accept, console, label, max_attempts=10, context_index=None):
    """Generate and repair a proposal within a finite total model-call budget."""
    if max_attempts < 1:
        raise ValueError("--max-attempts must be positive")
    request = dict(request)
    policy_state = {}
    if context_index is not None:
        instructions += "\n\n" + DISCOVERY_RULES
        request["context_kinds"] = list(context_index.records())
    discovery = DiscoverySession(context_index) if context_index is not None else None
    model_calls = 0
    def generate(prompt):
        nonlocal model_calls
        if enabled('bounded_repair') and model_calls >= positive_setting('MAX_DESIGN_CALLS', 32):
            raise RuntimeError(f'{label}: B3 logical model-call limit reached after {model_calls} calls')
        model_calls += 1
        with task_call(policy_state, attempt, 0):
            return model.generate_json(prompt, request)
    for attempt in range(1, max_attempts + 1):
        progress = f"{attempt}/{max_attempts}"
        console.show(f"{label} | Model proposal {progress}", "Generate the proposal; response-reading and obligation errors receive repair feedback.")
        response = None
        try:
            prompt = instructions if "correction" not in request else instructions + "\n\n" + REPAIR_INSTRUCTIONS
            if "correction" in request:
                correction = request["correction"]
                prompt += "\nActual failure: " + correction["error"]
                if correction.get("details"):
                    prompt += "\nRepair details:\n" + json.dumps(correction["details"], ensure_ascii=False, indent=2)
            response = generate(prompt)
            while context_index is not None and isinstance(response, dict) and "context_request" in response:
                query = response["context_request"]
                console.show(label + " | Context query", json.dumps(query, ensure_ascii=False))
                request["context_result"] = discovery.resolve(query)
                request["context_records"] = discovery.evidence
                request["context_candidates"] = discovery.candidates
                response = generate(prompt)
            accepted = accept(response)
            checkpoint(task=label, action=f"Accept design proposal {attempt}",
                details={"attempt": attempt, "sections": list(response) if isinstance(response, dict) else []})
            return accepted, response
        except ContextBudgetExceeded:
            raise
        except RESPONSE_ERRORS as error:
            feedback = response_feedback(error, response)
            feedback["failed_attempt"] = attempt
            checkpoint(task=label, action=f"Reject design proposal {attempt}", status="REJECTED", details=feedback)
            console.show(f"{label} | Repair feedback", json.dumps(feedback, ensure_ascii=False, indent=2))
            if attempt >= max_attempts:
                raise RuntimeError(f"{label} exhausted {max_attempts} proposals: {feedback['error']}") from error
            request["correction"] = feedback
