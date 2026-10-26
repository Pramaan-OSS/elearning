<template>
	<Popover bare>
		<template #trigger="{ open, setOpen }">
			<slot v-bind="{ open, setOpen }"></slot>
		</template>
		<template #default>
			<div
				class="absolute start-1/2 mt-3 w-96 max-w-lg -translate-x-1/2 transform rounded-6 bg-surface-base px-4 sm:px-0 lg:max-w-3xl"
			>
				<div
					class="overflow-hidden rounded-6 p-3 shadow-2xl ring-1 ring-outline-gray-2"
				>
					<FileUploader
						:fileTypes="['image/*']"
						:private="false"
						:validateFile="validateFile"
						@success="(file) => saveImage(file)"
					>
						<template v-slot="{ file, progress, uploading, openFileSelector }">
							<div class="flex items-center justify-center gap-x-2">
								<Button @click="openFileSelector" :loading="uploading">
									{{
										uploading
											? __('Uploading {0}%').format(progress)
											: __('Upload Image')
									}}
								</Button>
							</div>
						</template>
					</FileUploader>
                    <form @submit.prevent="searchPhotos" class="mt-3">
                        <label for="cover-photo-query">{{ __('Search licensed photos') }}</label>
                        <input id="cover-photo-query" v-model="query" class="w-full rounded border p-2" required maxlength="300">
                        <Button type="submit" :loading="searching">{{ __('Search photos') }}</Button>
                    </form>
                    <p class="text-sm">{{ __('Not yet live-verified') }}</p>
                    <p role="alert">{{ photoMessage }}</p>
                    <div class="max-h-80 overflow-auto">
                        <div v-for="photo in photos" :key="photo.url" class="my-3">
                            <button type="button" @click="emit('select', safeUrl(photo.url))"><img :src="safeUrl(photo.previewUrl)" :alt="photo.attribution" class="h-24 w-full object-cover"></button>
                            <p>{{ photo.attribution }} — <a :href="safeUrl(photo.authorUrl)" target="_blank" rel="noopener noreferrer">{{ photo.author }}</a></p>
                            <a :href="safeUrl(photo.sourceCreditUrl)" target="_blank" rel="noopener noreferrer">{{ photo.sourceCredit }}</a> ·
                            <a :href="safeUrl(photo.sourceUrl)" target="_blank" rel="noopener noreferrer">{{ __('Source') }}</a> ·
                            <a :href="safeUrl(photo.licenceUrl)" target="_blank" rel="noopener noreferrer">{{ photo.licence }}</a>
                        </div>
                        <Button v-if="nextPage" @click="searchPhotos(nextPage)">{{ __('More photos') }}</Button>
                    </div>
				</div>
			</div>
		</template>
	</Popover>
</template>
<script setup>
import { Popover, FileUploader, Button, call } from 'frappe-ui'
import { ref } from 'vue'
import { safeUrl } from '@/utils/safeUrl'
const query = ref('')
const photos = ref([])
const nextPage = ref(null)
const photoMessage = ref('')
const searching = ref(false)
let lastQuery = ''
const searchPhotos = async (page = 1) => {
 if(typeof page !== 'number' || query.value !== lastQuery) page = 1
 searching.value = true; photoMessage.value = ''
 try {
  const result = await call('lms.integrations.photos.search', {query: query.value, page})
  photos.value = page === 1 ? result.results : [...photos.value, ...result.results]
  lastQuery = query.value; nextPage.value = result.nextPage
  if (!photos.value.length) photoMessage.value = __('No photos found.')
 } catch {photoMessage.value = __('Photo search is not available yet. Try again later.')}
 finally {searching.value = false}
}

const emit = defineEmits(['select'])

const validateFile = (file) => {
	const extension = file.name.split('.').pop().toLowerCase()
	if (!['jpg', 'jpeg', 'png'].includes(extension)) {
		return __('Only image file is allowed.')
	}
}

const saveImage = (file) => {
	emit('select', file.file_url)
}
</script>
