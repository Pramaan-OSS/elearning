<template>
	<details class="rounded-6 border border-outline-gray-2 p-4">
		<summary class="cursor-pointer text-p-base-medium">{{ __('Translate course draft') }}</summary>
		<div class="mt-4 space-y-3">
			<label class="block">{{ __('Course text') }}
				<select v-model="field" class="block rounded border p-2">
					<option value="title">{{ __('Title') }}</option>
					<option value="short_introduction">{{ __('Short introduction') }}</option>
					<option value="description">{{ __('Description') }}</option>
				</select>
			</label>
			<label class="block">{{ __('Translate into (for example en, de, pt-br)') }}
				<input v-model="language" class="block rounded border p-2" />
			</label>
			<p>{{ __('Review the draft before copying it into your course. Nothing saves automatically.') }}</p>
			<button type="button" :disabled="busy" class="rounded border px-3 py-2" @click="translate">{{ busy ? __('Working...') : __('Translate') }}</button>
			<p v-if="error" role="alert">{{ error }}</p>
			<label v-if="draft" class="block">{{ __('Translation draft') }}
				<textarea :value="draft" readonly rows="8" class="block w-full rounded border p-2" />
			</label>
		</div>
	</details>
</template>
<script setup>
import { ref } from 'vue'
import { call } from 'frappe-ui'
const props = defineProps({ course: { type: Object, required: true } })
const field = ref('title')
const language = ref('')
const busy = ref(false)
const draft = ref('')
const error = ref('')
async function translate() {
	error.value = ''
	draft.value = ''
	const content = new DOMParser().parseFromString(String(props.course[field.value] || ''), 'text/html').body.textContent || ''
	if (!content.trim() || content.length > 5000 || !language.value.trim()) {
		error.value = __('Choose course text up to 5000 characters and give a target language.')
		return
	}
	busy.value = true
	try {
		const result = await call('lms.lms.author_tools.translate_content', { content, target_language: language.value })
		draft.value = result?.text || ''
		if (!draft.value) error.value = __('The translation came back empty. Try again.')
	} catch (failure) {
		error.value = failure?.messages?.[0] || failure?.message || __('Translation is not available yet.')
	} finally {
		busy.value = false
	}
}
</script>
