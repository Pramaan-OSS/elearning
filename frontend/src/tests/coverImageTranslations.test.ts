// The cover-image picker is upload-only since image search is not available
// yet: the popover's wording is what a translator now sees.
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('frappe-ui', () => ({
	createResource: () => ({ submit: () => Promise.resolve({}) }),
	Popover: { template: '<div><slot name="trigger" /><slot /></div>' },
	FileUploader: {
		template:
			'<div><slot :file="null" :progress="0" :uploading="false" :openFileSelector="() => {}" /></div>',
	},
	Button: { template: '<button><slot /></button>' },
}))

import EditCoverImage from '@/components/Modals/EditCoverImage.vue'

describe('cover-image translations', () => {
	it('says image search is unavailable and offers the upload', () => {
		const wrapper = mount(EditCoverImage, {
			global: {
				mocks: { __: (text: string) => text },
			},
		})
		const html = wrapper.html()
		expect(html).toContain('Image search is not available yet')
		expect(html).toContain('Upload Image')
		expect(html).not.toContain('Unsplash')
		expect(html).not.toContain('search by keyword')
	})
})
