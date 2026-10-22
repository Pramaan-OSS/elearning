import { describe, expect, it, vi } from 'vitest'

const { submit } = vi.hoisted(() => ({ submit: vi.fn() }))
vi.mock('frappe-ui', () => ({ createResource: () => ({ submit }) }))
import { runOnRunner } from '../pages/ProgrammingExercises/liveCode'

describe('code runner availability', () => {
	it('shows a plain refusal and allows a later run to succeed', async () => {
		const options = { runtime: 'python', code: 'print(1)', stdin: '', onStderr: vi.fn() }
		submit.mockRejectedValueOnce(new Error('/api/method/internal.run ValidationError'))
		await expect(runOnRunner(options)).rejects.toThrow(
			'The code runner could not be reached, so nothing was saved. Please try again.'
		)
		submit.mockResolvedValueOnce({ stdout: '1\n', stderr: '' })
		await expect(runOnRunner(options)).resolves.toBe('1')
		expect(submit).toHaveBeenLastCalledWith({ runtime: 'python', code: 'print(1)', stdin: '' })
	})
})
