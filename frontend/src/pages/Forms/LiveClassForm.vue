<template>
	<FormShell
		:title="__('New Live Class')"
		size="xl"
		position="top"
		@close="close"
	>
		<template #default>
			<div v-if="loadingBatch" class="p-4 text-base text-ink-gray-6">
				{{ __('Loading...') }}
			</div>
			<div v-else-if="refusal" class="p-4 text-base text-ink-gray-6">
				{{ refusal }}
			</div>
			<div v-else data-testid="live-class-fields" class="flex flex-col gap-4">
				<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
					<div class="space-y-4">
						<FormControl
							type="text"
							v-model="liveClass.title"
							:label="__('Title')"
							:required="true"
						/>
						<FormControl
							v-model="liveClass.date"
							type="date"
							:format="dateFormat"
							:label="__('Date')"
							:required="true"
						/>
						<FormControl
							type="number"
							v-model="liveClass.duration"
							:label="__('Duration (in minutes)')"
							:required="true"
						/>
					</div>
					<div class="space-y-4">
						<Tooltip
							:text="
								__(
									'Time must be in 24 hour format (HH:mm). Example 11:30 or 22:00'
								)
							"
						>
							<FormControl
								v-model="liveClass.time"
								type="time"
								:label="__('Time')"
								:required="true"
							/>
						</Tooltip>

						<Combobox
							:modelValue="liveClass.timezone"
							:options="getTimezoneOptions()"
							:label="__('Timezone')"
							:required="true"
							@update:modelValue="(value) => (liveClass.timezone = value)"
						/>
						<FormControl
							v-model="liveClass.auto_recording"
							type="select"
							:options="getRecordingOptions()"
							:label="__('Auto Recording')"
						/>
					</div>
				</div>
				<FormControl
					v-model="liveClass.description"
					type="textarea"
					:label="__('Description')"
				/>
			</div>
		</template>
		<template #actions>
			<div
				v-if="!refusal && !loadingBatch"
				class="flex items-center justify-end"
			>
				<HeaderButton
					data-testid="live-class-save"
					:label="__('Create')"
					variant="solid"
					:loading="createLiveClass.loading"
					@click="submitLiveClass()"
				/>
			</div>
		</template>
	</FormShell>
</template>
<script setup>
import {
	Combobox,
	createResource,
	getCachedListResource,
	Tooltip,
	FormControl,
	toast,
} from 'frappe-ui'
import { computed, reactive, inject, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getTimezones, getUserTimezone } from '@/utils/'
import FormShell from '@/components/FormShell.vue'
import HeaderButton from '@/components/HeaderButton.vue'
import {
	batchRouteLocation,
	useBatchDetails,
} from '@/composables/useBatchForms'
import { useFormRoute } from '@/composables/useFormRoute'
import { submitResource } from '@/utils/resource'
import { getDateFormat } from '@/utils/format'

const props = defineProps({
	batchName: {
		type: String,
		required: true,
	},
})

const user = inject('$user')
const dayjs = inject('$dayjs')
const route = useRoute()
const readOnlyMode = window.read_only_mode
const dateFormat = getDateFormat()

// C2: close()'s pop branch restores the hash by itself; its deep-link branch
// replaces to this literal location, so the tab hash has to be carried here or
// a close lands on the bare path and silently resets the page to tab 0.
const { close } = useFormRoute(
	batchRouteLocation('BatchDetail', props.batchName, route.hash)
)

// Its own fetch, NOT the page's instance — see useBatchForms.ts for why
// sharing one is not available here.
const batch = useBatchDetails(() => props.batchName)

const loadingBatch = computed(() => !batch.data && batch.loading)

// can_schedule_classes, not the Batch Evaluator role or can_manage:
// create_live_class accepts only the batch's instructors.
const isAdmin = computed(() =>
	Boolean(user.data?.is_moderator || batch.data?.can_schedule_classes)
)

const refusal = computed(() => {
	if (readOnlyMode) return __('This site is in read-only mode.')
	if (!isAdmin.value)
		return __(
			"You can't schedule live classes for this batch. Ask one of its instructors or a Moderator."
		)
	return null
})

const liveClass = reactive({
	title: '',
	description: '',
	date: '',
	time: '',
	duration: '',
	timezone: '',
	auto_recording: 'No Recording',
	batch: props.batchName,
	host: user.data?.name,
})

onMounted(() => {
	liveClass.timezone = getUserTimezone()
})

const getTimezoneOptions = () => {
	return getTimezones().map((timezone) => {
		return {
			label: timezone,
			value: timezone,
		}
	})
}

const getRecordingOptions = () => {
	return [
		{
			label: 'No Recording',
			value: 'No Recording',
		},
		{
			label: 'Cloud',
			value: 'Cloud',
		},
	]
}

const createLiveClass = createResource({
	url: 'lms.lms.doctype.lms_batch.lms_batch.create_live_class',
	makeParams(values) {
		return {
			doctype: 'LMS Live Class',
			batch_name: values.batch,
			...values,
		}
	},
})

// C4: the `reloadLiveClasses` defineModel is gone with the modal, so the tab's
// list is refreshed by name instead. A lookup, NOT createListResource — a
// constructor here would win the cache and hand LiveClass.vue an instance with
// this file's (absent) filters/fields, because createListResource discards the
// second caller's options. Null when the tab is not mounted (deep link), which
// is correct: it fetches on mount anyway. Mirrors stores/notifications.js:35.
const reloadLiveClassList = () => {
	getCachedListResource(['liveClasses', props.batchName])?.reload()
}

const submitLiveClass = () => {
	if (refusal.value) return
	return submitResource(createLiveClass, liveClass, {
		// Returned, so a missing field blocks the submit with its own message. It
		// used to be discarded, and an empty duration reached the server as an
		// Internal Server Error.
		validate() {
			return validateFormFields()
		},
		onSuccess() {
			reloadLiveClassList()
			close()
		},
		onError(err) {
			toast.error(err.messages?.[0] || err)
			console.error(err)
		},
	})
}

const validateFormFields = () => {
	if (!liveClass.title) {
		return __('Please enter a title.')
	}
	if (!liveClass.date) {
		return __('Please select a date.')
	}
	if (!liveClass.time) {
		return __('Please select a time.')
	}
	if (!liveClass.timezone) {
		return __('Please select a timezone.')
	}
	if (!valideTime()) {
		return __('Please enter a valid time in the format HH:mm.')
	}
	const liveClassDateTime = dayjs(`${liveClass.date}T${liveClass.time}`).tz(
		liveClass.timezone,
		true
	)
	if (
		liveClassDateTime.isSameOrBefore(
			dayjs().tz(liveClass.timezone, false),
			'minute'
		)
	) {
		return __('Please select a future date and time.')
	}
	if (!liveClass.duration) {
		return __('Please select a duration.')
	}
}

const valideTime = () => {
	let time = liveClass.time.split(':')
	// HH:mm from the picker, or HH:mm:ss when seconds are typed.
	if (time.length < 2 || time.length > 3) {
		return false
	}
	if (time[0] < 0 || time[0] > 23) {
		return false
	}
	if (time[1] < 0 || time[1] > 59) {
		return false
	}
	return true
}
</script>
