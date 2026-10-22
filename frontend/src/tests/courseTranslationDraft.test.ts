import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CourseTranslationDraft from '@/components/Courses/CourseTranslationDraft.vue'
const global = { mocks: { __: (text: string) => text } }
const { call } = vi.hoisted(() => ({ call: vi.fn() }))
vi.mock('frappe-ui', () => ({ call }))
beforeEach(() => { call.mockReset() })
it('requests a course draft through the server and leaves the course unchanged', async () => {
	const course = { title: 'Hello', description: '<p>Course body</p>' }
	call.mockResolvedValue({ text: 'Hallo' })
	const wrapper = mount(CourseTranslationDraft, { props: { course }, global })
	await wrapper.find('input').setValue('de')
	await wrapper.find('button').trigger('click')
	await flushPromises()
	expect(call).toHaveBeenCalledWith('lms.lms.author_tools.translate_content', { content: 'Hello', target_language: 'de' })
	expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('Hallo')
	expect(course.title).toBe('Hello')
	expect(call).toHaveBeenCalledTimes(1)
	wrapper.unmount()
})
it('offers the course description and shows an honest unavailable response', async () => {
	call.mockRejectedValue(new Error('Translation is not available yet.'))
	const wrapper = mount(CourseTranslationDraft, { props: { course: { description: '<p>Course body</p>' } }, global })
	await wrapper.find('select').setValue('description')
	await wrapper.find('input').setValue('fr')
	await wrapper.find('button').trigger('click')
	await flushPromises()
	expect(call.mock.calls[0][1].content).toBe('Course body')
	expect(wrapper.get('[role="alert"]').text()).toContain('not available yet')
	expect(wrapper.find('textarea').exists()).toBe(false)
	wrapper.unmount()
})
