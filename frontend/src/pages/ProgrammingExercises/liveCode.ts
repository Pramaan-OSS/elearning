import { createResource } from 'frappe-ui'

// One sandboxed run of the learner's code, on the app's own runner endpoint.
// The page stays on its origin: nothing here talks to a code-execution
// service directly.
const runner = createResource({
	url: 'lms.lms.code_runner.run_code',
	makeParams: ({ runtime, code, stdin }: { runtime: string; code: string; stdin: string }) => ({
		language: runtime,
		code,
		stdin,
	}),
})

type RunnerResult = { stdout?: string; stderr?: string }

// Runs `code` once against `stdin` and resolves with its trimmed stdout.
export function runOnRunner(options: {
	runtime: string
	code: string
	stdin: string
	onStderr: (text: string) => void
}): Promise<string> {
	return runner
		.submit({
			runtime: options.runtime,
			code: options.code,
			stdin: options.stdin,
		})
		.then((result: RunnerResult) => {
			const stderr = (result.stderr ?? '').trim()
			if (stderr) options.onStderr(stderr)
			return (result.stdout ?? '').trim()
		})
		.catch(() => {
			throw new Error(
				'The code runner could not be reached, so nothing was saved. Please try again.'
			)
		})
}
