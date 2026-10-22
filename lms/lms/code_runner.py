"""Runs a learner's code through the single Pramaan client, so a saved verdict
comes from code the server ran itself rather than from outputs the browser
reports.

Each case runs the way the exercise page shows it: the code as the source file,
the case's input fed to stdin, under the platform's sandbox time limit.
"""

from concurrent.futures import ThreadPoolExecutor

import frappe
from frappe import _

from lms.pramaan import PramaanClient, PramaanError

# The sandbox stops a program after 10 seconds by default; 20 is the most the
# platform allows.
RUN_TIMEOUT = 20
MAX_PARALLEL_RUNS = 5

# The stdin-reading preamble the exercise page starts a learner's code from.
# Keep in sync with BOILERPLATE in frontend/src/pages/ProgrammingExercises/exerciseRunFlow.ts.
BOILERPLATE = {
	"python": 'with open("stdin", "r") as f:\n    data = f.read()\n\ninputs = data.split() if len(data) else []\n\n# inputs is a list of strings\n# write your code below\n\n',
	"javascript": "const fs = require('fs');\n\nlet input = fs.readFileSync('/app/stdin', 'utf8').trim();\nconst inputs = input.split(\"\\n\");\n// inputs is an array of strings\n// write your code below\n",
}


class RunnerUnavailable(Exception):
	"""Raised inside a worker thread, where frappe.throw has no request to report to."""


def client():
	return PramaanClient()


def run_test_cases(language: str, code: str, test_cases: list) -> list[str]:
	"""Return each case's stdout, in the order of `test_cases`."""
	if not test_cases:
		return []

	runtime = (language or "python").lower()
	inputs = [case.input or "" for case in test_cases]

	try:
		with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_RUNS, len(inputs))) as pool:
			return list(pool.map(lambda stdin: run_once(runtime, code, stdin), inputs))
	except RunnerUnavailable:
		frappe.throw(_("The code runner could not be reached, so nothing was saved. Please try again."))


def code_to_store(language: str, starter_code: str | None, code: str) -> str:
	"""Submissions store the learner's code without the preamble, which the page
	adds back on load. Starter code replaces the preamble, so it is stored whole,
	as is code whose preamble the learner edited. A submission's full_code flag
	records which, since the stored code alone cannot tell them apart."""
	if starter_code:
		return code
	preamble = BOILERPLATE.get((language or "").lower(), "")
	if preamble and code.startswith(preamble):
		return code[len(preamble) :]
	return code


def run_once(runtime: str, code: str, stdin: str) -> str:
	stdout, _stderr = run_on_platform(runtime, code, stdin)
	return stdout


def run_on_platform(runtime: str, code: str, stdin: str, *, request_path: bool = False) -> tuple[str, str]:
	"""One sandboxed run. Returns its stdout and stderr.

	Errors are raised as RunnerUnavailable inside worker threads, and as plain
	messages on the request path.
	"""
	try:
		payload = {
			"language": runtime,
			"code": code,
			"timeLimitSeconds": RUN_TIMEOUT,
		}
		if stdin:
			payload["stdin"] = stdin
		result = client().call(
			"code.run",
			payload,
			idempotency_key=frappe.generate_hash(),
		)
	except PramaanError as error:
		if request_path:
			frappe.throw(_(str(error)))
		raise RunnerUnavailable from error
	return result.get("stdout") or "", result.get("stderr") or ""


@frappe.whitelist(methods=["POST"])
def run_code(language: str, code: str, stdin: str = "") -> dict:
	"""Run a learner's code once against one input, for the Run button."""
	runtime = (language or "python").lower()
	stdout, stderr = run_on_platform(runtime, code, stdin, request_path=True)
	return {"stdout": stdout, "stderr": stderr}
