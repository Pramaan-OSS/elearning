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
					<!-- Image search is not available yet: covers come from the
					     person's own uploads. -->
					<div
						class="mt-2 w-[25.5rem] rounded-4 border border-dashed p-4 text-center text-sm text-ink-gray-6"
					>
						{{ __('Image search is not available yet. Upload your own image.') }}
					</div>
				</div>
			</div>
		</template>
	</Popover>
</template>
<script setup>
import { Popover, FileUploader, Button } from 'frappe-ui'

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
