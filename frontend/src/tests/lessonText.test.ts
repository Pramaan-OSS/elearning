import { describe, expect, it } from 'vitest'
import { mediaUrlsFromBlocks, plainTextFromBlocks } from '@/utils/lessonText'

describe('lessonText', () => {
	it('collects block text in order and strips markup', () => {
		const blocks = [
			{ type: 'header', data: { text: '<b>Intro</b>' } },
			{ type: 'paragraph', data: { text: '  One   two  ' } },
			{ type: 'list', data: { items: ['first', '<i>second</i>'] } },
			{ type: 'code', data: { code: 'print(1)' } },
		]
		expect(plainTextFromBlocks(blocks as any)).toBe(
			'Intro\n\nOne two\n\nfirst\n\nsecond\n\nprint(1)'
		)
	})

	it('answers empty for nothing to translate', () => {
		expect(plainTextFromBlocks([])).toBe('')
		expect(plainTextFromBlocks(null)).toBe('')
		expect(plainTextFromBlocks([{ type: 'image', data: { url: 'x' } }])).toBe('')
	})

	it('lists only audio and video links, deduplicated', () => {
		const blocks = [
			{ type: 'video', data: { url: '/files/a.mp4' } },
			{ type: 'audio', data: { file: { url: '/files/b.mp3' } } },
			{ type: 'video', data: { url: '/files/a.mp4' } },
			{ type: 'embed', data: { url: 'https://school.example/page' } },
		]
		expect(mediaUrlsFromBlocks(blocks as any)).toEqual(['/files/a.mp4', '/files/b.mp3'])
	})
	it('finds media in the upload block saved by the lesson editor', () => {
		expect(mediaUrlsFromBlocks([
			{ type: 'upload', data: { file_url: '/private/files/lesson.wav' } },
			{ type: 'upload', data: { file_url: '/private/files/lesson.wav' } },
			{ type: 'upload', data: { file_url: '/private/files/notes.pdf' } },
		])).toEqual(['/private/files/lesson.wav'])
	})
})
