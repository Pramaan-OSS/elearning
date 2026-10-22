// Plain text and media links out of a lesson's EditorJS blocks, for the
// author-assistance actions. Both are read-only over the saved shape.

type Block = {
	type?: string
	data?: {
		text?: string
		items?: string[]
		content?: string
		caption?: string
		url?: string
		file_url?: string
		file?: { url?: string }
		code?: string
		title?: string
	}
}

const TEXT_FIELDS = ['text', 'content', 'caption', 'title', 'code'] as const

// One string a translator can work with, in block order.
export function plainTextFromBlocks(blocks: Block[] | null | undefined): string {
	if (!Array.isArray(blocks)) return ''
	const parts: string[] = []
	for (const block of blocks) {
		const data = block?.data
		if (!data) continue
		for (const field of TEXT_FIELDS) {
			const value = data[field]
			if (typeof value === 'string' && value.trim()) {
				parts.push(value.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim())
			}
		}
		if (Array.isArray(data.items)) {
			for (const item of data.items) {
				if (typeof item === 'string' && item.trim()) {
					parts.push(item.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim())
				}
			}
		}
	}
	return parts.join('\n\n')
}

// The lesson's own audio and video links, in block order, deduplicated.
export function mediaUrlsFromBlocks(blocks: Block[] | null | undefined): string[] {
	if (!Array.isArray(blocks)) return []
	const seen = new Set<string>()
	const urls: string[] = []
	for (const block of blocks) {
		const data = block?.data
		if (!data) continue
		const url = data.file_url || data.url || data.file?.url
		if (typeof url === 'string' && url && !seen.has(url)) {
			seen.add(url)
			urls.push(url)
		}
	}
	return urls.filter((url) => /\.(mp3|m4a|wav|ogg|oga|webm|mp4|m4v|mov)(\?|$)/i.test(url))
}
