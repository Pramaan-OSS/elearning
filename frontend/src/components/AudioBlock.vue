<template>
	<div>
		<audio ref="audio" @ended="handleAudioEnd" @loadedmetadata="duration = audio.duration" controlsList="nodownload" class="mb-4">
			<source :src="safeUrl(encodeURI(file))" />
		</audio>
		<div
			data-testid="audio-player"
			class="flex items-center gap-x-2 rounded-7 overflow-hidden p-1 w-1/2"
		>
			<Button
				variant="ghost"
				:label="isPlaying ? __('Pause') : __('Play')"
				@click="togglePlay"
			>
				<template #icon>
					<span :class="isPlaying ? 'lucide-pause' : 'lucide-play'" class="w-4 h-4 text-ink-gray-9" />
				</template>
			</Button>
			<input
				type="range"
				min="0"
				:max="duration"
				step="0.1"
				v-model="currentTime"
				@input="changeCurrentTime"
				:aria-label="__('Seek')"
				class="duration-slider w-full h-1"
			/>
			<span class="text-xs-medium text-ink-gray-9">
				{{ formatTime(currentTime) }} / {{ formatTime(duration) }}
			</span>
			<Button
				variant="ghost"
				:label="isMuted ? __('Unmute') : __('Mute')"
				@click="toggleMute"
			>
				<template #icon>
					<span :class="isMuted ? 'lucide-volume-x' : 'lucide-volume-2'" class="w-4 h-4 text-ink-gray-9" />
				</template>
			</Button>
		</div>
	</div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Button } from 'frappe-ui'
import { safeUrl } from '@/utils/safeUrl'

const isPlaying = ref(false)
const audio = ref(null)
let isMuted = ref(false)
let currentTime = ref(0)
let duration = ref(0)

const props = defineProps({
	file: {
		type: String,
		required: true,
	},
})


const togglePlay = () => {
	isPlaying.value = !isPlaying.value
}

const toggleMute = () => {
	audio.value.muted = !audio.value.muted
	isMuted.value = audio.value.muted
}

const changeCurrentTime = () => {
	audio.value.currentTime = currentTime.value
}

const handleAudioEnd = () => {
	isPlaying.value = false
}

const formatTime = (time) => {
	const minutes = Math.floor(time / 60)
	const seconds = Math.floor(time % 60)
	return `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`
}

watch(isPlaying, (newVal) => {
	if (newVal) {
		audio.value.play().catch(() => { isPlaying.value = false })
	} else {
		audio.value.pause()
	}
})
</script>
<style>
.duration-slider {
	flex: 1;
	-webkit-appearance: none;
	appearance: none;
	background-color: var(--surface-gray-4);
	cursor: pointer;
}

.duration-slider::-webkit-slider-thumb {
	height: 10px;
	width: 10px;
	-webkit-appearance: none;
	background-color: var(--surface-gray-10);
}

@media screen and (-webkit-min-device-pixel-ratio: 0) {
	input[type='range'] {
		overflow: hidden;
		width: 150px;
		-webkit-appearance: none;
	}

	input[type='range']::-webkit-slider-thumb {
		-webkit-appearance: none;
		cursor: pointer;
		box-shadow: -150px 0 0 150px var(--surface-gray-10);
	}
}
</style>
