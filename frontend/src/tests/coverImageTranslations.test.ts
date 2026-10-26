// Both upload and licensed photo search keep their labels translatable.
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('frappe-ui', () => ({
	call: () => Promise.resolve({results: []}),
	Popover: { template: '<div><slot name="trigger" /><slot /></div>' },
	FileUploader: {
		template:
			'<div><slot :file="null" :progress="0" :uploading="false" :openFileSelector="() => {}" /></div>',
	},
	Button: { template: '<button><slot /></button>' },
}))

import EditCoverImage from '@/components/Modals/EditCoverImage.vue'

describe('cover-image translations', () => {
	it('offers licensed search and upload with the verification notice', () => {
		const wrapper = mount(EditCoverImage, {
			global: {
				mocks: { __: (text: string) => text },
			},
		})
		const html = wrapper.html()
		expect(html).toContain('Search licensed photos')
		expect(html).toContain('Not yet live-verified')
		expect(html).toContain('Upload Image')
		expect(html).not.toContain('Unsplash')
		expect(html).not.toContain('search by keyword')
	})
})
